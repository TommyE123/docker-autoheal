import { useState, useSyncExternalStore } from "react";
import { Alert, Badge, Button, Collapse, Table } from "react-bootstrap";

const INSTALL_URL = "https://github.com/TommyE123/docker-autoheal#readme";

function useEngineVersion(engine) {
  const [store] = useState(() => {
    let version = 0;
    return {
      subscribe: (onChange) =>
        engine.subscribe(() => {
          version += 1;
          onChange();
        }),
      getSnapshot: () => version,
    };
  });
  return useSyncExternalStore(store.subscribe, store.getSnapshot);
}

function stateBadge(container) {
  if (container.quarantined) return <Badge bg="danger">quarantined</Badge>;
  if (!container.running) return <Badge bg="secondary">stopped</Badge>;
  return <Badge bg="success">running</Badge>;
}

function faultLabel(fault) {
  if (fault === "crashloop") return "crashes after every start";
  if (fault === "unhealthy") return "health check failing";
  return "working";
}

/**
 * Demo-only banner: says the environment is simulated, which version it shows,
 * and lets the visitor break or fix the simulated containers.
 */
// The demo's state lives only in memory, so a reload is a reset to the seed
// state, and every page (Events, Notifications, Config load once) refetches.
const reloadPage = () => window.location.reload();

export default function DemoBanner({ engine, version, onReset = reloadPage }) {
  useEngineVersion(engine);
  // Open on wide screens; on phones the controls would push the app off-screen.
  const [open, setOpen] = useState(
    () => window.matchMedia?.("(min-width: 992px)").matches ?? true,
  );
  const containers = engine.describe();
  const { monitor, restart } = engine.config;

  return (
    <Alert variant="info" className="mb-0 rounded-0 border-0 border-bottom">
      <div className="d-flex flex-wrap align-items-center gap-2">
        <i className="bi bi-joystick" aria-hidden="true" />
        <strong>Simulated demo: no real containers.</strong>
        <span>
          Showing <code>{version}</code>.
        </span>
        <a href={INSTALL_URL} target="_blank" rel="noreferrer">
          Install Autoheal
        </a>
        <span className="ms-auto d-flex gap-2">
          <Button
            size="sm"
            variant="outline-primary"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            aria-controls="demo-controls"
          >
            {open ? "Hide controls" : "Try it"}
          </Button>
          <Button size="sm" variant="outline-secondary" onClick={onReset}>
            <i
              className="bi bi-arrow-counterclockwise me-1"
              aria-hidden="true"
            />
            Reset demo
          </Button>
        </span>
      </div>
      <Collapse in={open}>
        <div id="demo-controls">
          <p className="small mt-2 mb-2">
            Break a container below and watch Autoheal react in the table and on
            the Events page. The demo uses shorter timings than the defaults
            (checks every {monitor.interval_seconds}s,{" "}
            {restart.cooldown_seconds}s cooldown, quarantine after{" "}
            {restart.max_restarts} restarts); change them on the Config page. A
            quarantined container is left alone: fix its app, then restart it
            from the table, and Autoheal releases it once it has stayed healthy.
          </p>
          <Table size="sm" responsive className="mb-0 small align-middle">
            <thead>
              <tr>
                <th scope="col">Container</th>
                <th scope="col">State</th>
                <th scope="col">App</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {containers.map((c) => (
                <tr key={c.name}>
                  <td>
                    <code>{c.name}</code>
                    {!c.monitored && (
                      <span className="text-muted"> (not monitored)</span>
                    )}
                  </td>
                  <td>{stateBadge(c)}</td>
                  <td>{faultLabel(c.fault)}</td>
                  <td>
                    <div className="d-flex flex-wrap gap-1">
                      {c.running &&
                        c.healthcheck &&
                        c.fault !== "unhealthy" && (
                          <Button
                            size="sm"
                            variant="outline-warning"
                            onClick={() => engine.failHealthCheck(c.name)}
                          >
                            Fail health check
                          </Button>
                        )}
                      {c.running && (
                        <Button
                          size="sm"
                          variant="outline-danger"
                          onClick={() => engine.crash(c.name)}
                        >
                          Crash
                        </Button>
                      )}
                      {c.running && c.fault !== "crashloop" && (
                        <Button
                          size="sm"
                          variant="outline-danger"
                          onClick={() => engine.startCrashLoop(c.name)}
                        >
                          Crash loop
                        </Button>
                      )}
                      {c.running && (
                        <Button
                          size="sm"
                          variant="outline-secondary"
                          onClick={() => engine.stopCleanly(c.name)}
                        >
                          Stop (exit 0)
                        </Button>
                      )}
                      {c.fault && (
                        <Button
                          size="sm"
                          variant="outline-success"
                          onClick={() => engine.fix(c.name)}
                        >
                          Fix app
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      </Collapse>
    </Alert>
  );
}
