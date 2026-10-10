// Thin, guarded access to Docker for the UI E2E fixtures.
//
// The isolated environment is the Dev Container's own Docker-in-Docker daemon (PR #461)
// or, in CI, the ephemeral GitHub-hosted runner's own daemon; this module does not create
// another one. Every Docker command goes
// through `docker()`, which first proves the daemon is that isolated one and refuses
// to run anything otherwise, so the suite can never act on a host or production daemon.
import { execFile } from "node:child_process";
import os from "node:os";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export const IMAGE = "alpine:3.22";
// Marks every container the suite creates, so teardown can remove exactly those.
export const RUN_LABEL = "autoheal.e2e.run";

let isolation;

// Same checks as .devcontainer/verify-isolation.sh: a dockerd process exists in this
// environment, and the daemon's own name is this machine's hostname (true only when
// the client is bound to that local daemon). A remote DOCKER_HOST/DOCKER_CONTEXT is
// rejected outright.
async function evaluateIsolation() {
  for (const variable of ["DOCKER_HOST", "DOCKER_CONTEXT"]) {
    if (process.env[variable]) {
      return { ok: false, reason: `${variable} is set` };
    }
  }
  try {
    await execFileAsync("pgrep", ["-x", "dockerd"]);
  } catch {
    return {
      ok: false,
      reason: "no dockerd process runs in this environment",
    };
  }
  let daemonName;
  try {
    const { stdout } = await execFileAsync(
      "docker",
      ["info", "--format", "{{.Name}}"],
      { timeout: 30000 },
    );
    daemonName = stdout.trim();
  } catch (error) {
    return {
      ok: false,
      reason: `the Docker daemon is unreachable (${error.message})`,
    };
  }
  if (daemonName !== os.hostname()) {
    return {
      ok: false,
      reason: `Docker daemon '${daemonName}' is not this environment's own daemon ('${os.hostname()}')`,
    };
  }
  return { ok: true };
}

export function checkIsolatedDocker() {
  if (!isolation) {
    isolation = evaluateIsolation();
  }
  return isolation;
}

export async function assertIsolatedDocker() {
  const result = await checkIsolatedDocker();
  if (!result.ok) {
    throw new Error(
      `Refusing to use Docker: ${result.reason}. UI E2E tests that need Docker only run ` +
        "against an isolated local daemon: the Dev Container's Docker-in-Docker daemon " +
        "or the CI runner's own " +
        "(docs/developer/testing.md#ui-e2e-suite-playwright).",
    );
  }
}

export async function docker(args, options = {}) {
  await assertIsolatedDocker();
  const { stdout } = await execFileAsync("docker", args, {
    timeout: 120000,
    ...options,
  });
  return stdout.trim();
}

function labelArgs(labels) {
  return Object.entries(labels).flatMap(([key, value]) => [
    "--label",
    `${key}=${value}`,
  ]);
}

/**
 * Starts a detached container. Returns without error when a container of that name
 * already exists, which is how workers share one set of read-only containers: the
 * first to create it wins and the others reuse it.
 */
export async function startContainer({
  name,
  runId,
  labels = {},
  options = [],
  command,
}) {
  try {
    await docker([
      "run",
      "-d",
      "--name",
      name,
      "--restart",
      "no",
      // PID 1 ignores SIGTERM unless it handles it, so without an init process a plain
      // `sleep` makes every stop or restart wait out Docker's 10 second grace period.
      "--init",
      ...labelArgs({ [RUN_LABEL]: runId, ...labels }),
      ...options,
      IMAGE,
      ...command,
    ]);
  } catch (error) {
    if (!/already in use/i.test(`${error.stderr || ""}${error.message}`)) {
      throw error;
    }
  }
}

export function inspectContainer(name, format) {
  return docker(["inspect", "--format", format, name]);
}

export function stopContainer(name) {
  return docker(["stop", "--time", "1", name]);
}

export function removeNamed(names) {
  return docker(["rm", "-f", ...names]);
}

export async function removeContainers(filter) {
  const ids = await docker(["ps", "-aq", ...filter]);
  if (ids) {
    await docker(["rm", "-f", ...ids.split("\n")]);
  }
}
