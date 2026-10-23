/* global process */
// Runs once in the main process before worker pools start, so setting TZ
// here (unlike setupFiles or test.env) actually reaches Date in every pool.
// See https://vitest.dev/guide/common-errors#time-zone-does-not-change-in-worker-threads
export default function () {
  process.env.TZ = "UTC";
}
