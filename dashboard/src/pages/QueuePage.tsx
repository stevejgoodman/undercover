import { api, statuses } from "../api";
import { DecisionChip, StatusChip } from "../components/Chips";
import { ClaimLink } from "../components/ClaimLink";
import { Message } from "../components/Message";
import { PageHeader } from "../components/PageHeader";
import { DispatchPanel } from "../components/DispatchPanel";
import { date, label, money, statusLabels } from "../format";
import { REFRESH_MS, useLoad } from "../useLoad";

export function QueuePage() {
  const { data: claims, error } = useLoad(api.listClaims, REFRESH_MS);
  if (!claims) return <Message error={error} />;

  return (
    <>
      <PageHeader
        title="Claims queue"
        lead="Every claim waiting to be decided and where it stands. A dispatch works the waiting claims and those left in progress, with the claim agents at once you choose."
      />
      <section className="tiles" aria-label="Claims by state">
        {statuses.map((status) => {
          const count = claims.filter((c) => c.status === status).length;
          return (
            <div
              className="panel tile"
              key={status}
              aria-label={`${statusLabels[status]}: ${String(count)}`}
            >
              <StatusChip status={status} />
              <span className="tile-count mono">{count}</span>
            </div>
          );
        })}
      </section>
      <DispatchPanel />
      <section className="panel table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Claim</th>
              <th>Customer</th>
              <th>Type</th>
              <th>Summary</th>
              <th className="num">Claimed</th>
              <th>Submitted</th>
              <th>State</th>
              <th>Decision</th>
              <th className="num">Payout</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((claim) => (
              <tr key={claim.claim_id}>
                <td className="nowrap">
                  <ClaimLink claimId={claim.claim_id} />
                </td>
                <td>{claim.customer_name}</td>
                <td>{label(claim.claim_type)}</td>
                <td>{claim.summary}</td>
                <td className="num mono">{money(claim.amount_claimed)}</td>
                <td className="nowrap">{date(claim.submitted_on)}</td>
                <td>
                  <StatusChip status={claim.status} />
                </td>
                <td>
                  {claim.decision && <DecisionChip decision={claim.decision} />}
                </td>
                <td className="num mono">
                  {claim.payout !== null && money(claim.payout)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
