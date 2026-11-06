#!/usr/bin/env bash
# The Documentation Drift Detection focus areas, shared by .github/scripts/docs-drift-reads.sh
# (which plans the reads) and .github/scripts/docs-drift-coverage.sh (which checks them). Both
# rebuild the file list from the checkout and the week number, so nothing the agent can write
# decides what counts as read. Source this file from the checkout root; it defines
# docs_drift_area, which sets area_name and files for an ISO week number.
#
# Each week has one focus area (the last digit of the week number, modulo 5): documentation
# files and the app source that implements what they describe. The areas together cover the
# user documentation, the architecture documents, the deployment files and every app source
# directory that holds code. README.md is read in every area: it makes claims about all of
# them, and the agent only judges a claim whose implementation it read. Entries ending in a
# slash are directories: their non-empty .py files, tests excluded, are all read.

docs_drift_area() {
  local week=$1 area p f
  if [[ ! $week =~ ^[0-9]+$ ]]; then
    echo "::error::Week '$week' is not a number" >&2
    return 1
  fi
  area=$((10#$week % 10 % 5))
  local paths=()
  case $area in
    0)
      area_name="Configuration and deployment"
      paths=(README.md docs/user/configuration.md docs/user/installation.md docs/user/migration.md
        docker-compose.yml Dockerfile app/main.py app/config/)
      ;;
    1)
      area_name="Health checks and recovery"
      paths=(README.md docs/user/health-checks.md docs/user/labels.md docs/user/maintenance-mode.md
        app/monitor/ app/docker_client/)
      ;;
    2)
      area_name="API, UI and architecture"
      paths=(README.md docs/user/usage.md docs/developer/architecture.md
        docs/developer/project-structure.md app/api/)
      ;;
    3)
      area_name="Metrics, logging and troubleshooting"
      paths=(README.md docs/user/monitoring-and-metrics.md docs/user/troubleshooting.md app/main.py
        app/config/config_manager.py app/api/routes/health.py app/api/routes/healthchecks.py)
      ;;
    4)
      area_name="Notifications and Uptime Kuma"
      paths=(README.md docs/user/notifications.md app/notifications/ app/uptime_kuma/
        app/monitor/uptime_kuma_monitor.py)
      ;;
  esac

  files=()
  for p in "${paths[@]}"; do
    if [[ $p == */ ]]; then
      if [[ ! -d $p ]]; then
        echo "::error::Directory $p of focus area '$area_name' not found" >&2
        return 1
      fi
      while IFS= read -r f; do files+=("$f"); done < <(find "$p" -path app/tests -prune -o -name '*.py' -size +0 -print | LC_ALL=C sort)
    elif [[ -f $p ]]; then
      files+=("$p")
    else
      echo "::error::File $p of focus area '$area_name' not found" >&2
      return 1
    fi
  done
  if ((${#files[@]} == 0)); then
    echo "::error::No files in focus area '$area_name'" >&2
    return 1
  fi
}
