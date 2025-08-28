# GitHub Actions Migration Checklist

This checklist helps you migrate from the old workflows to the optimized ones.

## ✅ Pre-Migration Steps

### 1. Repository Configuration
- [ ] **Branch Protection Rules**: Update required status checks to match new job names
  - Old: `test-build` → New: `lint-and-quality`, `test`, `docker-build`, `results`
  - Old: `lint` → New: Integrated into `lint-and-quality`
- [ ] **Secrets Configuration**: Ensure required secrets are set
  - [ ] `GITHUB_TOKEN` (automatically available)
  - [ ] `CODECOV_TOKEN` (optional, for coverage reporting)
  - [ ] `KUBECONFIG_STAGING` (if using Kubernetes deployment)
  - [ ] `KUBECONFIG_PRODUCTION` (if using Kubernetes deployment)

### 2. Dependencies
- [ ] **Install act for local testing**: `brew install act` (macOS) or equivalent
- [ ] **Verify file paths**: Ensure all referenced files exist
  - [ ] `requirements-dev.txt`
  - [ ] `services/inference/requirements.txt`
  - [ ] `docker-compose.yml`
  - [ ] `tests/e2e/docker-compose.test.yml`

### 3. Backup
- [ ] **Backup existing workflows**: Copy old `.github/workflows/` to a backup location
- [ ] **Document custom configurations**: Note any custom settings to be preserved

## ✅ Migration Steps

### 1. File Changes
- [ ] **Remove old lint.yml**: `rm .github/workflows/lint.yml` (integrated into ci.yml)
- [ ] **Update workflows**: The new optimized workflows are in place
- [ ] **Add new security workflow**: `security.yml` is now available
- [ ] **Add composite actions**: New reusable actions in `.github/actions/`

### 2. Configuration Updates
- [ ] **Update Makefile**: If any make targets reference old workflow names
- [ ] **Update documentation**: Any docs referencing old workflow behavior
- [ ] **Update external integrations**: Services expecting old workflow names

### 3. Testing
- [ ] **Test workflows locally**:
  ```bash
  # Test workflow syntax
  act --list
  
  # Test specific job (dry-run)
  act --container-architecture linux/amd64 --job detect-changes --dryrun
  ```

- [ ] **Validate YAML syntax**:
  ```bash
  python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['ci.yml', 'cd.yml', 'docs.yml', 'security.yml', 'e2e-observability.yml']]"
  ```

## ✅ Post-Migration Validation

### 1. Initial Workflow Runs
- [ ] **Test CI workflow**: Create a test PR to trigger the new CI pipeline
- [ ] **Test documentation**: Make a documentation change to test docs workflow
- [ ] **Test security scanning**: Manually trigger security workflow
- [ ] **Test E2E workflow**: Manually trigger E2E observability tests

### 2. Monitoring
- [ ] **Check GitHub Actions tab**: Verify workflows are running
- [ ] **Review job summaries**: Check the new step summaries feature
- [ ] **Check Security tab**: Verify security scans are uploading SARIF results
- [ ] **Review artifacts**: Confirm artifacts are being generated and retained

### 3. Performance Validation
- [ ] **Compare build times**: New workflows should be faster due to caching
- [ ] **Check cache usage**: Verify caches are being created and used
- [ ] **Monitor resource usage**: Ensure no unexpected resource consumption

## ✅ Feature Adoption

### 1. New Capabilities to Use
- [ ] **Security scanning**: Review findings in GitHub Security tab
- [ ] **Performance testing**: Check performance test results in CI
- [ ] **Multi-environment deployment**: Use staging → production pipeline
- [ ] **Comprehensive reporting**: Utilize step summaries for insights
- [ ] **Matrix testing**: Leverage multiple Python versions on main branch

### 2. Workflow Customization
- [ ] **Adjust cache keys**: Customize for your specific file patterns
- [ ] **Configure matrix strategies**: Adjust Python versions as needed
- [ ] **Set up notifications**: Add Slack/email notifications for failures
- [ ] **Tune timeouts**: Adjust based on your service complexity

## ✅ Troubleshooting Common Issues

### 1. If Workflows Fail to Start
- [ ] Check YAML syntax: `act --list`
- [ ] Verify file paths in workflow files
- [ ] Check required secrets are set
- [ ] Review branch protection rule conflicts

### 2. If Builds Are Slow
- [ ] Check cache hit rates in build logs
- [ ] Verify cache keys are constructed correctly
- [ ] Consider adjusting matrix strategies
- [ ] Review Docker layer caching

### 3. If Tests Fail
- [ ] Check if test file paths have changed
- [ ] Verify test dependencies are installed
- [ ] Check Docker Compose configuration
- [ ] Review environment variable changes

### 4. If Security Scans Fail
- [ ] Check if security tools can be installed
- [ ] Review ignore patterns in configurations
- [ ] Verify SARIF upload permissions
- [ ] Check for tool version compatibility

## ✅ Performance Benchmarks

Track these metrics to validate the improvements:

| Metric | Before | Target After | Actual After |
|--------|--------|-------------|-------------|
| **CI Duration** | ~10 min | ~6 min | __ min |
| **Cache Hit Rate** | 0% | >80% | __% |
| **Security Coverage** | Basic linting | 4 scan types | __ types |
| **Parallel Jobs** | 1-2 | 4-8 | __ jobs |
| **Artifact Retention** | None | 7-30 days | __ days |

## ✅ Success Criteria

Migration is successful when:
- [ ] All workflows pass without errors
- [ ] Build times are improved (target: 40% faster)
- [ ] Security scans are running and uploading results
- [ ] Caching is working (>80% hit rate)
- [ ] All tests pass in parallel execution
- [ ] Step summaries provide useful insights
- [ ] No functionality is lost from old workflows

## 🆘 Rollback Plan

If migration issues occur:

1. **Immediate Rollback**:
   ```bash
   # Restore old workflows from backup
   cp backup/.github/workflows/* .github/workflows/
   git add .github/workflows/
   git commit -m "Rollback to old workflows"
   git push
   ```

2. **Partial Rollback**:
   - Keep new security.yml (no conflicts with old workflows)
   - Revert specific problematic workflows only
   - Maintain new composite actions (they don't affect old workflows)

3. **Investigation**:
   - Review GitHub Actions logs
   - Check act local testing results
   - Consult troubleshooting section in main documentation

## 📞 Support

If you encounter issues:

1. **Check the documentation**: `docs/github-actions-optimization.md`
2. **Review troubleshooting guide**: Section in the main documentation
3. **Test locally**: Use `act` to debug workflow issues
4. **Community resources**: GitHub Actions documentation and community forums

---

**Remember**: This migration brings significant improvements in security, performance, and maintainability. Take time to understand and leverage the new capabilities!
