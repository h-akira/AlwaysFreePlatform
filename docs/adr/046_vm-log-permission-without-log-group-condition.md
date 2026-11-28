# 046 VM のログの権限は、ロググループで絞らない

- 決めた日: 2026-11-28

## 背景

ADR 043 は、「VM の権限は、そのロググループにログを送ることだけを足す」と決めた。そのため、`use log-content` の文に、ロググループ `loggroup-afp-apps` で絞る条件（`where target.loggroup.id = ...`）を付けた。

本番で試すと、VM のエージェントが設定を取りに行く要求（`GetGeneratedUnifiedAgentConfiguration`）が `404 NotAuthorizedOrNotFound` で断られ、ログが送られなかった。Audit に残った要求には、ロググループが入っていなかった。

この ADR は、ADR 043 の権限の部分だけを改める。ほかの部分は変えない。

## 決定

- VM の動的グループの権限は、条件の無い次の 1 文にする。

  ```text
  Allow dynamic-group dg-afp-vm to use log-content in compartment <afp のコンパートメント>
  ```

## 理由

- 公式の例は、どれも条件の無いこの形である（[Managing Logs](https://docs.oracle.com/en-us/iaas/Content/Logging/Task/managinglogs.htm)）。
- `use log-content` には、ログを送る権限と、エージェントの設定を作る権限（`UNIFIED_AGENT_CONFIG_GENERATE`）の両方が入っている（[Logging の権限の一覧](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/loggingpolicyreference.htm)）。
- 条件に使った変数がその要求に当てはまらないと、条件は偽になり、要求は断られる（[Conditions](https://docs.oracle.com/en-us/iaas/Content/Identity/policysyntax/conditions.htm)）。設定を取る要求はロググループを対象にしないので、ロググループの条件で断られたと考えられる（文書の一般の決まりに当てはめた推測）。
- 条件を外したあと、エージェントは設定を取れるようになり、ログが `log-afp-apps` に届いた。

## 採らなかった案

| 案 | 理由 |
|---|---|
| ロググループで絞った文を残し、設定を取る権限だけを足す（`where request.permission = 'UNIFIED_AGENT_CONFIG_GENERATE'`。文が 2 つ） | ほかのログには送れないままにできるが、この形で設定を取れるかの公式の例が無い。文も 2 つに増える |

## 引き換え

- VM は、このコンパートメントのほかのログにも送れ、検索もできる。今あるほかのログは、DevOps のビルドのログ（`loggroup-afp-devops`）だけである。
- VM は、もともと DB の管理者のパスワードなども読める立場なので、増える危なさは小さいと判断した。
