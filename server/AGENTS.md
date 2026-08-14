# Server Agent Scope

Code under `server/` is private backend implementation. An Agent working in the
local repository may inspect, edit, test, and commit it as part of an
authorized source task; this does not require a remote FactorTester login,
`server_maintenance` role, or Aliyun SSH access.

The server-derived `server_backend_code` authority is required when an Agent
uses a protected server runtime path to apply or validate a backend change.
Remote publication, service reload, Docker/WireGuard/SSH maintenance, and
rollback are a separate release operation and require explicit deployment
authorization plus the remote administrator/Aliyun transport credential.

Use the private
[`factortester-server-maintenance` Skill](skills/factortester-server-maintenance/SKILL.md) for a concrete
authorized Maintenance Case. The Skill progressively loads the relevant
backend, Graph-governance or database reference. Follow
[FactorTester server maintenance](../docs/agents/factortester-server-maintenance.md) as the domain
contract. In particular:

- trust a passing Backend Assurance Gate and do not start a verifier routinely;
- use the compact maintenance-case resume packet, not the full Active Graph;
- inspect the real runtime path only after a concrete anomaly or capability gap;
- load approved diagnostic or implementation Skills progressively and execute
  a newly discovered Skill only after its conversation approval;
- back up and integrity-check affected databases before schema mutation;
- keep diagnosis, implementation, independent review, rollout, and rollback
  evidence separately attributable.

Never return source, database paths, credentials, proprietary factors, complete
artifacts, or maintenance instructions through the public client protocol.
