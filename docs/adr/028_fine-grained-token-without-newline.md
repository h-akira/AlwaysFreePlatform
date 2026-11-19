# 028 DevOps が GitHub を読むトークンは fine-grained にし、Vault には改行の無い base64 で入れる

- 決めた日: 2026-11-19

## 背景

ADR 023 で、DevOps が GitHub を読むトークンを基盤で 1 本の fine-grained にした。fine-grained のトークンで DevOps が 500 で失敗したので ADR 025 で classic にし、そのあと ADR 027 で 025 を取り消して、種類を原因が分かるまで未決にした。

この ADR は、ADR 027 を置き換える（027 が取り消した ADR 025 は、取り消したまま）。

失敗の原因は、トークンの種類ではなく、Vault のシークレットに入れた base64 の途中の改行だった。GNU coreutils の `base64` は、既定で 76 文字ごとに改行を入れる。fine-grained のトークンは長く、base64 にすると 76 文字を超えるので改行が入り、DevOps はその値を使えない（[references/oci-devops.md](../references/oci-devops.md) §3）。

## 決定

- トークンは fine-grained にする（ADR 023 のとおり）。対象は基盤に載せるプロジェクトのリポジトリだけ、権限は Contents の読み取りだけ。
- 管理者がトークンを Vault に入れるときは、改行の無い base64 を渡す（例: `base64 | tr -d '\n'`）。
- 基盤のコードが Vault に値を入れるところ（`scripts/triggers.py`）は、今のまま（Python の `base64.b64encode` は改行を入れない）。

## 理由

- 原因はトークンの種類でなかったので、ADR 023 の理由（対象のリポジトリを選べ、読み取りだけにできる）が、そのまま当たる。

## 採らなかった案

| 案 | 理由 |
|---|---|
| classic のトークン（`repo`） | 失敗の原因はトークンの種類ではなかった。classic は、持ち主のすべての非公開のリポジトリを読み書きできる |
