---
layout: post
title: Rollback Playbook
date: 2024-08-26 12:00:00 +0000
categories: [Operations, Playbooks]
tags: [rollback, deployment, operations]
pin: true
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

