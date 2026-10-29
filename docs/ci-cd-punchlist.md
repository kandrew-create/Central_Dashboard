# CI/CD pipeline punchlist

This checklist tracks CI/CD work for the SCADA Collector and Central Server. As of 28 October 2026, the repository has no CI/CD workflows. All items below remain pending.

- [ ] **Create GitHub Actions workflows** for pull requests, pushes to `main`, and manual runs.
- [ ] **Run Python tests** on supported versions: 3.12 and 3.13.
- [ ] **Run PostgreSQL 17 integration tests** against disposable databases; ensure database tests actually execute.
- [ ] **Add Windows checks** for DPAPI credentials, file permissions, HTTPS certificates, setup import/export, and both GUIs.
- [ ] **Make acceptance checks portable.** Existing helpers under ignored `.tools/` depend on this PC's paths and test cluster.
- [ ] **Build Python distributions** and verify migrations and configuration templates are included.
- [ ] **Build both Windows installers** using PyInstaller and Inno Setup, then smoke-test the packaged applications.
- [ ] **Validate Docker deployment** with image builds, Compose validation, migrations, API health, and worker processing.
- [ ] **Add security checks** for dependencies, accidentally committed secrets, and workflow configuration.
- [ ] **Audit release contents** to exclude credentials, databases, logs, and local settings.
- [ ] **Publish build evidence** including test reports, installers, and SHA-256 checksums.
- [ ] **Add a release workflow** that publishes tested artifacts from version tags and checks version consistency.
- [ ] **Harden workflow execution** with minimal permissions, pinned actions, timeouts, and cancellation of superseded runs.
- [ ] **Document deployment and recovery** before adding automated deployment to a hosting target.

Start with automated tests, portable database checks, and both installer builds. See [operations and recovery](operations.md) for existing deployment procedures and [Windows setup](central-server-windows.md) for Central Server commissioning requirements.
