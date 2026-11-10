import { Alert, Button } from "react-bootstrap";

const INSTALL_URL = "https://github.com/TommyE123/docker-autoheal#readme";

const reloadPage = () => window.location.reload();

/** Demo-only banner: says the data is sample data and which version this is. */
export default function DemoBanner({ version, onReset = reloadPage }) {
  return (
    <Alert
      variant="info"
      className="mb-0 rounded-0 border-0 border-bottom d-flex flex-wrap align-items-center gap-2"
    >
      <strong>Demo with sample data: no real containers.</strong>
      <span>
        Showing <code>{version}</code>. Changes last until you reload.
      </span>
      <a href={INSTALL_URL} target="_blank" rel="noreferrer">
        Install Autoheal
      </a>
      <Button
        size="sm"
        variant="outline-secondary"
        className="ms-auto"
        onClick={onReset}
      >
        Reset demo
      </Button>
    </Alert>
  );
}
