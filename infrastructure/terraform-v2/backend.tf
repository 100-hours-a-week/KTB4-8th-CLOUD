terraform {
  backend "s3" {
    bucket              = "keepgo-terraform-602601433533-ap-northeast-2-an"
    key                 = "v2/prod/terraform.tfstate"
    region              = "ap-northeast-2"
    encrypt             = true
    use_lockfile        = true
    allowed_account_ids = ["602601433533"]
  }
}