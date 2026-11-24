import { Card, Form, Button } from "react-bootstrap";

/**
 * ConfigImportExport Component
 * Handles configuration export and import functionality
 *
 * @param {Object} props - Component props
 * @param {Function} props.onExport - Callback when export is triggered
 * @param {Function} props.onImport - Callback when import file is selected
 * @param {boolean} [props.allowExport=true] - Whether export is enabled (ui.allow_export_json)
 * @param {boolean} [props.allowImport=true] - Whether import is enabled (ui.allow_import_json)
 */
function ConfigImportExport({
  onExport,
  onImport,
  allowExport = true,
  allowImport = true,
}) {
  return (
    <Card>
      <Card.Header>
        <h5 className="mb-0">
          <i className="bi bi-file-earmark-code me-2"></i>
          Configuration Export/Import
        </h5>
      </Card.Header>
      <Card.Body>
        <div className="mb-3">
          <Button
            variant="success"
            className="w-100 mb-2"
            onClick={onExport}
            disabled={!allowExport}
          >
            <i className="bi bi-download me-1"></i>
            Export Configuration
          </Button>
          <Form.Text className="d-block">
            {allowExport
              ? "Download current configuration as JSON file (includes Uptime Kuma settings)"
              : "Export is disabled (ui.allow_export_json)"}
          </Form.Text>
        </div>

        <div className="mb-3">
          <Form.Control
            type="file"
            accept=".json"
            onChange={onImport}
            id="importFile"
            disabled={!allowImport}
            aria-label="Import configuration file"
          />
          <Form.Text className="d-block mt-2">
            {allowImport
              ? "Upload configuration JSON file to restore all settings"
              : "Import is disabled (ui.allow_import_json)"}
          </Form.Text>
        </div>
      </Card.Body>
    </Card>
  );
}

export default ConfigImportExport;
