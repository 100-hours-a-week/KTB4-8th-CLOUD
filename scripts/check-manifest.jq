# production-manifest.json 형식 검사. validate.yaml과 release.sh가 함께 쓴다.
# 네 서비스의 40자리 커밋 SHA가 있어야 하고, 같은 FE 커밋에서 나오는 web·frontend는 SHA가 같아야 한다.
keys == ["images"]
and (.images | keys) == ["ai-api", "backend", "frontend", "web"]
and all(.images[]; type == "string" and test("^[0-9a-f]{40}$"))
and .images.web == .images.frontend
