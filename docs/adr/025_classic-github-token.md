# 025 DevOps が GitHub を読むトークンは、classic にする

- 決めた日: 2026-11-15

## 背景

ADR 023 で、DevOps が GitHub を読むトークンを基盤で 1 本にし、種類は fine-grained（読めるリポジトリを選べ、権限を Contents の読み取りだけにできるもの）にした。DevOps の文書の手順は classic で、fine-grained で読めるかは未確認だった。だめなら classic にすると書いた。

fine-grained のトークン（対象は hello のリポジトリだけ・Contents の読み取りだけ）では、DevOps の接続の検証も、ビルドでの `build_spec.yaml` の取得も、内部のエラー（500）で失敗した（[references/oci-devops.md](../references/oci-devops.md) §3）。

## 決定

- トークンは classic にする。権限は `repo`（非公開のリポジトリの読み取りに要る）。
- 基盤で 1 本にすることと、Vault のシークレットの作り方は、ADR 023 のまま。

## 理由

- OCI の権限は足りているのに、DevOps が GitHub に問い合わせる段で失敗する。DevOps が fine-grained のトークンを扱えないと判断した。
- DevOps の文書の手順は classic で、非公開のリポジトリには `repo` を付けるとされている。

## 採らなかった案

| 案 | 理由 |
|---|---|
| fine-grained のまま、原因を Oracle に問い合わせる | 文書が classic を前提にしており、直る時期も分からない |
| classic の `public_repo` にし、プロジェクトのリポジトリを公開にする | 権限は狭くなるが、非公開のリポジトリのプロジェクトを載せられない |

## 引き換え

- classic の `repo` は、対象のリポジトリを選べない。トークンの持ち主の、すべての非公開のリポジトリを読み書きできる。漏れたときの害は、ADR 023 の想定（選んだリポジトリを読まれるだけ）より大きい。期限を短めにして、入れ替えで抑える。
- ADR 023 の引き換えの「プロジェクトを足すたびに、トークンの対象にリポジトリを足す」は要らなくなる。
