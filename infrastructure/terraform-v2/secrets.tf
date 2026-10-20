# V1 Secret을 그대로 읽어 쓴다 -> ECS가 키 단위로 환경변수에 주입
# terraform은 조회만 한다. 값은 V1 Secret에서 관리하고 state에 남지 않는다.
# V1 정리 후에도 이 두 Secret은 지우면 안 된다.
data "aws_secretsmanager_secret" "app" {
  for_each = { backend = "Secret-v1-BE", ai-api = "Secret-v1-AI" }
  name     = each.value
}

locals {
  # V1 Secret에 실제로 있는 키만 삽입. 만약 하나라도 부족하면 Task 시작 안함
  secret_env_keys = {
    backend = ["GOOGLE_CLIENT_SECRET", "VWORLD_API_KEY"]
    ai-api  = ["GOOGLE_API_KEY", "NAVER_MAP_CLIENT_ID", "NAVER_MAP_CLIENT_SECRET", "SENTRY_DSN", "LANGSMITH_API_KEY"]
  }
  # V1과 같은 키 쌍 JWT만 환경변수가 아니라 PEM 파일로 읽기
  jwt_secret_keys = ["JWT_PUBLIC_KEY", "JWT_PRIVATE_KEY"]
  # V2 개발 DB 계정은 V1 Secret이 아니라 RDS 관리 Secret에서 읽는다
  db_secret_env = { DB_USERNAME = "username", DB_PASSWORD = "password" }
}