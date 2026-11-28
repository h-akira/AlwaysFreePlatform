# OCIR（OCI のコンテナ・レジストリ）

OCI のコンテナ・レジストリ（Oracle Cloud Infrastructure Registry）。AWS の ECR に当たる。

- **確かめた日**: 2026-11-14（ローカルと VM から実際に使った結果）
- 料金と無料枠は [oci-free-tier.md](oci-free-tier.md)。

## 1. 名前

- レジストリは `<リージョンのキー>.ocir.io`（例: `iad.ocir.io`）。イメージの名前は `<リージョンのキー>.ocir.io/<Object Storage の namespace>/<リポジトリ>:<タグ>`。
- リポジトリの名前には `/` を含められる（例: `repo-afp-app-a/web`）。
- 決めたコンパートメントにリポジトリを置くには、push の前に `oci artifacts container repository create --compartment-id <コンパートメント> --display-name <リポジトリ> --is-public false` で作る（作ったリポジトリへの push と pull が通った。実測）。

## 2. ログイン

auth token（ユーザに結び付く、期限の無いパスワード）を使わずに、OCI の資格からトークンを取ってログインできた（実測）。

```sh
oci raw-request --http-method GET --target-uri https://<リージョンのキー>.ocir.io/20180419/docker/token
# → {"data": {"token": "...", "expires_in": 3600}, ...}
printf '%s' "<token>" | docker login <リージョンのキー>.ocir.io -u BEARER_TOKEN --password-stdin
```

- ローカルの CLI のセッション（`--auth security_token`）でも、VM のインスタンス・プリンシパル（`--auth instance_principal`）でも通った。
- トークンの期限は 3600 秒。使う直前に毎回取る。
- VM（の dynamic group）に `Allow dynamic-group <名前> to read repos in compartment <名前>` を与えて、pull が通った（実測）。

## 3. マルチプラットフォームの一覧（index）は受け付けられなかった

- Docker Desktop の containerd のイメージストアでビルドすると、イメージは既定で **index**（本体のマニフェストと、来歴の証明 attestation のマニフェストをまとめた一覧）になる。
- これを push すると、層は上がったが、最後のマニフェストの登録で `409 Conflict` が返った。しかも、タグは **attestation のマニフェスト**（platform が `unknown/unknown`）を指した。そのイメージは動かせない（実測）。
- `BUILDX_NO_DEFAULT_ATTESTATIONS=1` を付けてビルドすると、index でなく 1 つのマニフェスト（`application/vnd.docker.distribution.manifest.v2+json`）になり、push も通った（実測）。
- 確かめたローカルの環境: Docker 27.5.1・buildx v0.20.1（Docker Desktop）。
