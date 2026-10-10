import { checkIsolatedDocker, removeContainers, RUN_LABEL } from "./docker.js";

// Containers the monitoring engine auto-selected or the tests explicitly (de)selected
// are recorded by name in the app's configuration; drop those references so repeated
// local runs do not accumulate entries in the dev stack's data directory.
async function removeConfigReferences(baseURL, runId) {
  const marker = `e2e-ui-${runId}-`;
  const response = await fetch(`${baseURL}/api/config`);
  if (!response.ok) {
    return;
  }
  const config = await response.json();
  const keep = (name) => !name.includes(marker);
  const { selected, excluded } = config.containers;
  if (selected.every(keep) && excluded.every(keep)) {
    return;
  }
  config.containers.selected = selected.filter(keep);
  config.containers.excluded = excluded.filter(keep);
  await fetch(`${baseURL}/api/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

export default async function globalTeardown(config) {
  const runId = process.env.UI_E2E_RUN_ID;
  if (!runId) {
    return;
  }
  try {
    await removeConfigReferences(config.projects[0].use.baseURL, runId);
  } catch (error) {
    console.warn(`UI E2E: could not tidy the app configuration: ${error}`);
  }
  if ((await checkIsolatedDocker()).ok) {
    await removeContainers(["--filter", `label=${RUN_LABEL}=${runId}`]);
  }
}
