# 구조 : 한 도메인 -> CloudFront가 경로로 분배 -> 페이지는 비공개 S3, /api 등은 ALB(CloudFront에서 오는 요청만 받음)
resource "aws_s3_bucket" "web" {
  bucket        = "${local.name}-web-${var.aws_account_id}"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true

}

resource "aws_s3_bucket_ownership_controls" "web" {
  bucket = aws_s3_bucket.web.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

# 이전 빌드를 30일 보관해 롤백에 쓰고, 그 뒤에는 지운다.
resource "aws_s3_bucket_versioning" "web" {
  bucket = aws_s3_bucket.web.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "web" {
  bucket = aws_s3_bucket.web.id

  rule {
    id     = "expire-old-builds"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration { noncurrent_days = 30 }
  }

  depends_on = [aws_s3_bucket_versioning.web]
}

# orgin 연결
resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${local.name}-web"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewerExceptHostHeader"
}

locals {
  # ALB 리스너 규칙과 같은 경로를 CloudFront도 ALB로 보낸다. 웹과 API가 한 도메인이라 CORS가 필요 없습니다.
  api_paths = flatten([for rule in local.listener_rules : rule.paths])
}

# ---------- 페이지 경로 → 파일 ----------
# Next 정적 export는 페이지마다 html이 생긴다: /home → /home.html, /mypage/profile → /mypage/profile.html
resource "aws_cloudfront_function" "web_router" {
  name    = "${local.name}-web-router"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      var uri = request.uri;

      if (uri === '/privacy-policy' || uri === '/privacy-policy/') {
        return {
          statusCode: 302,
          statusDescription: 'Found',
          headers: { location: { value: '${var.privacy_policy_url}' } }
        };
      }

      if (uri === '/') {
        request.uri = '/index.html';
        return request;
      }

      if (uri.endsWith('/')) {
        uri = uri.slice(0, -1);
      }

      if (uri.split('/').pop().indexOf('.') === -1) {
        request.uri = uri + '.html';
      }

      return request;
    }
  JS
}

# ---------- 배포 ----------
resource "aws_cloudfront_distribution" "web" {
  enabled         = true
  is_ipv6_enabled = true
  http_version    = "http2and3"
  price_class     = "PriceClass_200"
  aliases         = var.web_domain_name == "" ? [] : [var.web_domain_name]
  comment         = "${local.name} web"

  origin {
    origin_id                = "web"
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  origin {
    origin_id   = "api"
    domain_name = var.api_domain_name

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "https-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60
      origin_keepalive_timeout = 60
    }
  }

  # 페이지(HTML). 캐시 시간은 업로드할 때 붙이는 Cache-Control을 따른다.
  default_cache_behavior {
    target_origin_id       = "web"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
    compress               = true

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.web_router.arn
    }
  }

  # 빌드 해시가 붙은 JS·CSS. 오래 캐시해도 배포 때 파일명이 바뀐다.
  ordered_cache_behavior {
    path_pattern           = "/_next/static/*"
    target_origin_id       = "web"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
    compress               = true
  }

  dynamic "ordered_cache_behavior" {
    for_each = local.api_paths
    content {
      path_pattern             = ordered_cache_behavior.value
      target_origin_id         = "api"
      viewer_protocol_policy   = "redirect-to-https"
      allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods           = ["GET", "HEAD"]
      cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
      origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id
      compress                 = false
    }
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = var.web_domain_name == ""
    acm_certificate_arn            = var.web_domain_name == "" ? null : var.web_certificate_arn
    ssl_support_method             = var.web_domain_name == "" ? null : "sni-only"
    minimum_protocol_version       = var.web_domain_name == "" ? "TLSv1" : "TLSv1.2_2021"
  }
}

# CloudFront만 읽는다. ListBucket이 있어야 없는 파일이 403이 아니라 404로 나간다.
resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "CloudFrontRead"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = ["s3:GetObject", "s3:ListBucket"]
        Resource  = [aws_s3_bucket.web.arn, "${aws_s3_bucket.web.arn}/*"]
        Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.web.arn } }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.web.arn, "${aws_s3_bucket.web.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.web]
}