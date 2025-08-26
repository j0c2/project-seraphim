---
layout: default
title: Rollback Playbook
description: Safe model rollback strategies for Project Seraphim
parent: Playbooks
nav_order: 1
---

# Rollback Playbook

1. Freeze deploys.
2. Compare baseline vs. candidate canary metrics.
3. If SLO breached or canary fails, execute Helm rollback to the previous revision:
   ```bash
   helm rollback seraphim-inference --to-revision $(helm history -n seraphim seraphim-inference -o json | jq -r '.[-2].revision')
   ```
   Alternatively, run `helm history seraphim-inference -n seraphim` and choose a valid revision number manually.
4. Verify health and SLOs on Grafana.
5. Post-mortem notes in docs/playbooks/.

