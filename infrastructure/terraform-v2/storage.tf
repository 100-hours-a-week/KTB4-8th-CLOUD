# 구조 흐름 : 업로드 버킷(비공개) -> Backend Task Role(iam권한 받아야함) -> 환경변수... 당연히 service.tf
# 현재는 Backend가 파일을 넣고 지우며, 조회는 Backend가 만든 5분짜리 Presigned URL로 브라우저가 S3에서 직접 받는다.

resource "aws_s3_bucket" "uploads" {
  bucket        = "${local.name}-uploads-${var.aws_account_id}"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket              = aws_s3_bucket.uploads.id
  block_public_acls   = true
  block_public_policy = true

  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }

}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}