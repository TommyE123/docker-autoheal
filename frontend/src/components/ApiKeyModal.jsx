import { useId, useState } from "react";
import { Modal, Button, Form } from "react-bootstrap";

function ApiKeyModal({ show, rejected, hasKey, onSubmit, onClear, onCancel }) {
  const id = useId();
  const titleId = `${id}-api-key-title`;
  const inputId = `${id}-api-key-input`;
  const [value, setValue] = useState("");

  const handleSubmit = (event) => {
    event.preventDefault();
    const key = value.trim();
    if (!key) return;
    setValue("");
    onSubmit(key);
  };

  return (
    <Modal show={show} onHide={onCancel} centered aria-labelledby={titleId}>
      <Form onSubmit={handleSubmit}>
        <Modal.Header closeButton>
          <Modal.Title id={titleId}>API key required</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <p>
            This Autoheal instance requires an API key. The key is kept for this
            browser tab only.
          </p>
          {rejected && (
            <p className="text-danger" role="alert">
              The API key was rejected. Enter a valid key.
            </p>
          )}
          <Form.Group controlId={inputId}>
            <Form.Label>API key</Form.Label>
            <Form.Control
              type="password"
              autoComplete="off"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoFocus
            />
          </Form.Group>
        </Modal.Body>
        <Modal.Footer>
          {hasKey && (
            <Button
              variant="outline-danger"
              onClick={onClear}
              className="me-auto"
            >
              Clear stored key
            </Button>
          )}
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={!value.trim()}>
            Save key
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  );
}

export default ApiKeyModal;
