import { randomBytes } from "node:crypto";
import { checkIsolatedDocker, removeContainers, RUN_LABEL } from "./docker.js";

// Tags this run's containers so teardown removes exactly those. Workers inherit the
// variable because they are started after global setup.
export default async function globalSetup() {
  process.env.UI_E2E_RUN_ID = randomBytes(3).toString("hex");

  // Containers left behind by an interrupted earlier run. Best effort and only on a
  // verified isolated daemon: runs that need no Docker (and hosts without the
  // isolated daemon) skip this silently, and nothing here ever touches another daemon.
  if ((await checkIsolatedDocker()).ok) {
    await removeContainers(["--filter", `label=${RUN_LABEL}`]);
  }
}
