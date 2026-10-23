import { useState, useEffect, useCallback, useRef, useId } from "react";
import {
  Container,
  Row,
  Col,
  Card,
  Button,
  Form,
  Table,
  Modal,
  Alert,
  Badge,
  Spinner,
} from "react-bootstrap";
import {
  getNotificationsConfig,
  updateNotificationsConfig,
  addNotificationService,
  updateNotificationService,
  deleteNotificationService,
  testNotificationService,
  testUnsavedNotificationService,
} from "../services/api";
import { EVENT_TYPES } from "../constants/eventTypes";

// Fields required for each service type, beyond the always-required name.
// Mirrors the "*"-marked fields rendered by renderServiceFields() below.
const REQUIRED_FIELDS_BY_TYPE = {
  webhook: ["url"],
  discord: ["url"],
  slack: ["url"],
  telegram: ["bot_token", "chat_id"],
  ntfy: ["topic"],
  gotify: ["server_url", "app_token"],
  pushover: ["user_key", "api_token"],
};

function isServiceFormValid(formData) {
  const hasValue = (field) => String(formData[field] ?? "").trim() !== "";
  if (!hasValue("name")) return false;
  return (REQUIRED_FIELDS_BY_TYPE[formData.type] || []).every(hasValue);
}

// Fields sent for each service type, required and optional. Only non-empty values are sent;
// REQUIRED_FIELDS_BY_TYPE gates the buttons.
const FIELDS_BY_TYPE = {
  webhook: ["url", "headers"],
  discord: ["url", "username"],
  slack: ["url"],
  telegram: ["bot_token", "chat_id"],
  ntfy: ["topic", "server_url", "username", "password", "access_token"],
  gotify: ["server_url", "app_token"],
  pushover: ["user_key", "api_token"],
};

const hasPayloadValue = (value) =>
  typeof value === "object" && value !== null
    ? Object.keys(value).length > 0
    : Boolean(value);

// Only send the fields relevant to the service type.
function buildServicePayload(formData) {
  const payload = {
    name: formData.name,
    type: formData.type,
    enabled: formData.enabled,
  };
  for (const field of FIELDS_BY_TYPE[formData.type] || []) {
    if (hasPayloadValue(formData[field])) payload[field] = formData[field];
  }
  return payload;
}

function NotificationsPage() {
  const id = useId();
  const notificationSystemSwitchId = `${id}-notification-system`;
  const notificationSystemLabelId = `${id}-notification-system-label`;
  const modalTitleId = `${id}-notification-modal-title`;
  const controlId = (name) => `${id}-${name}`;
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [editingService, setEditingService] = useState(null);
  const [alert, setAlert] = useState({
    show: false,
    message: "",
    variant: "success",
  });
  const [testingService, setTestingService] = useState(null);
  const [testingForm, setTestingForm] = useState(false);
  const [modalAlert, setModalAlert] = useState(null);

  const serviceTypes = [
    { value: "webhook", label: "Generic Webhook" },
    { value: "discord", label: "Discord" },
    { value: "slack", label: "Slack" },
    { value: "telegram", label: "Telegram" },
    { value: "ntfy", label: "Ntfy" },
    { value: "gotify", label: "Gotify" },
    { value: "pushover", label: "Pushover" },
  ];

  const [formData, setFormData] = useState({
    name: "",
    type: "webhook",
    enabled: true,
    url: "",
    headers: {},
    username: "",
    password: "",
    bot_token: "",
    chat_id: "",
    topic: "",
    server_url: "",
    access_token: "",
    app_token: "",
    user_key: "",
    api_token: "",
  });

  const alertTimeoutRef = useRef(null);
  // Bumped whenever the dialog opens or closes so a late test result is ignored.
  const testRequestRef = useRef(0);

  useEffect(() => () => clearTimeout(alertTimeoutRef.current), []);

  const showAlert = useCallback((message, variant = "success") => {
    setAlert({ show: true, message, variant });
    clearTimeout(alertTimeoutRef.current);
    alertTimeoutRef.current = setTimeout(
      () => setAlert({ show: false, message: "", variant: "success" }),
      5000,
    );
  }, []);

  const fetchConfig = useCallback(async () => {
    try {
      setLoading(true);
      const response = await getNotificationsConfig();
      setConfig(response.data);
    } catch (error) {
      console.error("Failed to fetch notifications config:", error);
      showAlert("Failed to load notifications configuration", "danger");
    } finally {
      setLoading(false);
    }
  }, [showAlert]);

  useEffect(() => {
    // Deferred so the initial load does not set state synchronously in the effect
    const initialLoad = setTimeout(fetchConfig, 0);
    return () => clearTimeout(initialLoad);
  }, [fetchConfig]);

  const handleToggleNotifications = async (enabled) => {
    try {
      setSaving(true);
      await updateNotificationsConfig({ enabled });
      setConfig({ ...config, enabled });
      showAlert(`Notifications ${enabled ? "enabled" : "disabled"}`, "success");
    } catch (error) {
      console.error("Failed to toggle notifications:", error);
      showAlert("Failed to update notifications", "danger");
    } finally {
      setSaving(false);
    }
  };

  const handleEventFiltersChange = async (selectedEvents) => {
    try {
      setSaving(true);
      await updateNotificationsConfig({ event_filters: selectedEvents });
      setConfig({ ...config, event_filters: selectedEvents });
      showAlert("Event filters updated", "success");
    } catch (error) {
      console.error("Failed to update event filters:", error);
      showAlert("Failed to update event filters", "danger");
    } finally {
      setSaving(false);
    }
  };

  const handleEventFilterToggle = (eventType) => {
    const current = config.event_filters || [];
    const updated = current.includes(eventType)
      ? current.filter((e) => e !== eventType)
      : [...current, eventType];
    handleEventFiltersChange(updated);
  };

  const handleOpenModal = (service = null) => {
    if (service) {
      setEditingService(service);
      setFormData({ ...service });
    } else {
      setEditingService(null);
      setFormData({
        name: "",
        type: "webhook",
        enabled: true,
        url: "",
        headers: {},
        username: "",
        password: "",
        bot_token: "",
        chat_id: "",
        topic: "",
        server_url: "",
        access_token: "",
        app_token: "",
        user_key: "",
        api_token: "",
      });
    }
    testRequestRef.current += 1;
    setTestingForm(false);
    setModalAlert(null);
    setShowModal(true);
  };

  const handleCloseModal = () => {
    testRequestRef.current += 1;
    setTestingForm(false);
    setModalAlert(null);
    setShowModal(false);
    setEditingService(null);
  };

  const handleSaveService = async () => {
    try {
      setSaving(true);

      const cleanedData = buildServicePayload(formData);

      if (editingService) {
        await updateNotificationService(editingService.name, cleanedData);
        showAlert("Notification service updated successfully", "success");
      } else {
        await addNotificationService(cleanedData);
        showAlert("Notification service added successfully", "success");
      }

      await fetchConfig();
      handleCloseModal();
    } catch (error) {
      // Log the message and status only: the full Axios error carries the request body, which
      // can include credentials such as the ntfy access token.
      console.error(
        "Failed to save service:",
        error.message,
        error.response?.status,
      );
      showAlert(
        error.response?.data?.detail || "Failed to save notification service",
        "danger",
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteService = async (serviceName) => {
    if (
      !window.confirm(
        `Are you sure you want to delete the service "${serviceName}"?`,
      )
    ) {
      return;
    }

    try {
      setSaving(true);
      await deleteNotificationService(serviceName);
      showAlert("Notification service deleted successfully", "success");
      await fetchConfig();
    } catch (error) {
      console.error("Failed to delete service:", error);
      showAlert("Failed to delete notification service", "danger");
    } finally {
      setSaving(false);
    }
  };

  const handleTestForm = async () => {
    const requestId = ++testRequestRef.current;
    const isStale = () => requestId !== testRequestRef.current;
    try {
      setTestingForm(true);
      setModalAlert(null);
      await testUnsavedNotificationService(buildServicePayload(formData));
      if (isStale()) return;
      setModalAlert({
        variant: "success",
        message: "Test notification sent successfully",
      });
    } catch (error) {
      if (isStale()) return;
      // Log the message and status only: the full Axios error carries the request body, which
      // can include credentials such as bot tokens and webhook URLs.
      console.error(
        "Failed to test service:",
        error.message,
        error.response?.status,
      );
      const detail = error.response?.data?.detail;
      setModalAlert({
        variant: "danger",
        message:
          typeof detail === "string"
            ? detail
            : "Failed to send test notification",
      });
    } finally {
      if (!isStale()) setTestingForm(false);
    }
  };

  const handleTestService = async (serviceName) => {
    try {
      setTestingService(serviceName);
      await testNotificationService(serviceName);
      showAlert(`Test notification sent to "${serviceName}"`, "success");
    } catch (error) {
      console.error("Failed to test service:", error);
      showAlert(
        error.response?.data?.detail || "Failed to send test notification",
        "danger",
      );
    } finally {
      setTestingService(null);
    }
  };

  const renderServiceFields = () => {
    switch (formData.type) {
      case "webhook":
        return (
          <>
            <Form.Group controlId={controlId("webhook-url")} className="mb-3">
              <Form.Label>Webhook URL *</Form.Label>
              <Form.Control
                type="url"
                value={formData.url || ""}
                onChange={(e) =>
                  setFormData({ ...formData, url: e.target.value })
                }
                placeholder="https://example.com/webhook"
                required
              />
            </Form.Group>
          </>
        );

      case "discord":
        return (
          <>
            <Form.Group
              controlId={controlId("discord-webhook-url")}
              className="mb-3"
            >
              <Form.Label>Discord Webhook URL *</Form.Label>
              <Form.Control
                type="url"
                value={formData.url || ""}
                onChange={(e) =>
                  setFormData({ ...formData, url: e.target.value })
                }
                placeholder="https://discord.com/api/webhooks/..."
                required
              />
            </Form.Group>
            <Form.Group
              controlId={controlId("discord-username")}
              className="mb-3"
            >
              <Form.Label>Username (optional)</Form.Label>
              <Form.Control
                type="text"
                value={formData.username || ""}
                onChange={(e) =>
                  setFormData({ ...formData, username: e.target.value })
                }
                placeholder="Docker Auto-Heal"
              />
            </Form.Group>
          </>
        );

      case "slack":
        return (
          <Form.Group
            controlId={controlId("slack-webhook-url")}
            className="mb-3"
          >
            <Form.Label>Slack Webhook URL *</Form.Label>
            <Form.Control
              type="url"
              value={formData.url || ""}
              onChange={(e) =>
                setFormData({ ...formData, url: e.target.value })
              }
              placeholder="https://hooks.slack.com/services/..."
              required
            />
          </Form.Group>
        );

      case "telegram":
        return (
          <>
            <Form.Group
              controlId={controlId("telegram-bot-token")}
              className="mb-3"
            >
              <Form.Label>Bot Token *</Form.Label>
              <Form.Control
                type="text"
                value={formData.bot_token || ""}
                onChange={(e) =>
                  setFormData({ ...formData, bot_token: e.target.value })
                }
                placeholder="123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
                required
              />
            </Form.Group>
            <Form.Group
              controlId={controlId("telegram-chat-id")}
              className="mb-3"
            >
              <Form.Label>Chat ID *</Form.Label>
              <Form.Control
                type="text"
                value={formData.chat_id || ""}
                onChange={(e) =>
                  setFormData({ ...formData, chat_id: e.target.value })
                }
                placeholder="123456789"
                required
              />
            </Form.Group>
          </>
        );

      case "ntfy":
        return (
          <>
            <Form.Group controlId={controlId("ntfy-topic")} className="mb-3">
              <Form.Label>Topic *</Form.Label>
              <Form.Control
                type="text"
                value={formData.topic || ""}
                onChange={(e) =>
                  setFormData({ ...formData, topic: e.target.value })
                }
                placeholder="docker-autoheal"
                required
              />
            </Form.Group>
            <Form.Group
              controlId={controlId("ntfy-server-url")}
              className="mb-3"
            >
              <Form.Label>Server URL (optional)</Form.Label>
              <Form.Control
                type="url"
                value={formData.server_url || ""}
                onChange={(e) =>
                  setFormData({ ...formData, server_url: e.target.value })
                }
                placeholder="https://ntfy.sh (default)"
              />
            </Form.Group>
            <Form.Group controlId={controlId("ntfy-username")} className="mb-3">
              <Form.Label>Username (optional)</Form.Label>
              <Form.Control
                type="text"
                value={formData.username || ""}
                onChange={(e) =>
                  setFormData({ ...formData, username: e.target.value })
                }
              />
            </Form.Group>
            <Form.Group controlId={controlId("ntfy-password")} className="mb-3">
              <Form.Label>Password (optional)</Form.Label>
              <Form.Control
                type="password"
                value={formData.password || ""}
                onChange={(e) =>
                  setFormData({ ...formData, password: e.target.value })
                }
              />
            </Form.Group>
            <Form.Group
              controlId={controlId("ntfy-access-token")}
              className="mb-3"
            >
              <Form.Label>Access token (optional)</Form.Label>
              <Form.Control
                type="password"
                value={formData.access_token || ""}
                onChange={(e) =>
                  setFormData({ ...formData, access_token: e.target.value })
                }
                placeholder="tk_..."
              />
              <Form.Text muted>
                Takes precedence over username/password.
              </Form.Text>
            </Form.Group>
          </>
        );

      case "gotify":
        return (
          <>
            <Form.Group
              controlId={controlId("gotify-server-url")}
              className="mb-3"
            >
              <Form.Label>Server URL *</Form.Label>
              <Form.Control
                type="url"
                value={formData.server_url || ""}
                onChange={(e) =>
                  setFormData({ ...formData, server_url: e.target.value })
                }
                placeholder="https://gotify.example.com"
                required
              />
            </Form.Group>
            <Form.Group
              controlId={controlId("gotify-app-token")}
              className="mb-3"
            >
              <Form.Label>App Token *</Form.Label>
              <Form.Control
                type="text"
                value={formData.app_token || ""}
                onChange={(e) =>
                  setFormData({ ...formData, app_token: e.target.value })
                }
                placeholder="AaBbCcDdEeFf"
                required
              />
            </Form.Group>
          </>
        );

      case "pushover":
        return (
          <>
            <Form.Group
              controlId={controlId("pushover-user-key")}
              className="mb-3"
            >
              <Form.Label>User Key *</Form.Label>
              <Form.Control
                type="text"
                value={formData.user_key || ""}
                onChange={(e) =>
                  setFormData({ ...formData, user_key: e.target.value })
                }
                placeholder="uQiRzpo4DXghDmr9QzzfQu27cmVRsG"
                required
              />
            </Form.Group>
            <Form.Group
              controlId={controlId("pushover-api-token")}
              className="mb-3"
            >
              <Form.Label>API Token *</Form.Label>
              <Form.Control
                type="text"
                value={formData.api_token || ""}
                onChange={(e) =>
                  setFormData({ ...formData, api_token: e.target.value })
                }
                placeholder="azGDORePK8gMaC0QOYAMyEEuzJnyUi"
                required
              />
            </Form.Group>
          </>
        );

      default:
        return null;
    }
  };

  if (loading) {
    return (
      <Container className="py-5 text-center">
        <Spinner animation="border" />
        <p className="mt-3">Loading notifications configuration...</p>
      </Container>
    );
  }

  return (
    <Container className="py-4">
      <Row className="mb-4">
        <Col>
          <h2>Notifications</h2>
          <p className="text-muted">
            Configure notification services to receive alerts for container
            events
          </p>
        </Col>
      </Row>

      {alert.show && (
        <Alert
          variant={alert.variant}
          dismissible
          className="alert-floating"
          onClose={() => setAlert({ ...alert, show: false })}
        >
          {alert.message}
        </Alert>
      )}

      <Row className="mb-4">
        <Col>
          <Card>
            <Card.Body>
              <div className="d-flex justify-content-between align-items-center">
                <div>
                  <h5>
                    <Form.Label
                      htmlFor={notificationSystemSwitchId}
                      id={notificationSystemLabelId}
                      className="mb-0"
                    >
                      Notification System
                    </Form.Label>
                  </h5>
                  <p className="text-muted mb-0">
                    {config?.enabled
                      ? "Notifications are enabled"
                      : "Notifications are disabled"}
                  </p>
                </div>
                <div className="d-flex align-items-center">
                  <Form.Check
                    id={notificationSystemSwitchId}
                    aria-labelledby={notificationSystemLabelId}
                    type="switch"
                    checked={config?.enabled || false}
                    onChange={(e) =>
                      handleToggleNotifications(e.target.checked)
                    }
                    disabled={saving}
                  />
                  <Form.Label
                    htmlFor={notificationSystemSwitchId}
                    className="ms-2 mb-0"
                  >
                    {config?.enabled ? "Enabled" : "Disabled"}
                  </Form.Label>
                </div>
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="mb-4">
        <Col>
          <Card>
            <Card.Header>
              <h5 className="mb-0">Event Filters</h5>
            </Card.Header>
            <Card.Body>
              <p className="text-muted">
                Select which event types should trigger notifications
              </p>
              <div className="d-flex flex-wrap gap-2">
                {EVENT_TYPES.map((eventType) => (
                  <Badge
                    key={eventType.value}
                    bg={
                      config?.event_filters?.includes(eventType.value)
                        ? "primary"
                        : "secondary"
                    }
                    style={{
                      cursor: "pointer",
                      fontSize: "0.9rem",
                      padding: "0.5rem 1rem",
                    }}
                    onClick={() => handleEventFilterToggle(eventType.value)}
                  >
                    {eventType.label}
                    {config?.event_filters?.includes(eventType.value) && " ✓"}
                  </Badge>
                ))}
              </div>
              {(!config?.event_filters ||
                config.event_filters.length === 0) && (
                <Alert variant="info" className="mt-3 mb-0">
                  No filters selected - all events will trigger notifications
                </Alert>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="mb-4">
        <Col>
          <Card>
            <Card.Header className="d-flex justify-content-between align-items-center">
              <h5 className="mb-0">Notification Services</h5>
              <Button
                variant="primary"
                size="sm"
                onClick={() => handleOpenModal()}
              >
                + Add Service
              </Button>
            </Card.Header>
            <Card.Body>
              {config?.services?.length === 0 ? (
                <Alert variant="info" className="mb-0">
                  No notification services configured. Click &quot;Add
                  Service&quot; to get started.
                </Alert>
              ) : (
                <Table responsive striped hover>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Type</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {config?.services?.map((service) => (
                      <tr key={service.name}>
                        <td>{service.name}</td>
                        <td>
                          <Badge bg="info">
                            {serviceTypes.find((t) => t.value === service.type)
                              ?.label || service.type}
                          </Badge>
                        </td>
                        <td>
                          <Badge bg={service.enabled ? "success" : "secondary"}>
                            {service.enabled ? "Enabled" : "Disabled"}
                          </Badge>
                        </td>
                        <td>
                          <Button
                            variant="outline-primary"
                            size="sm"
                            className="me-2"
                            onClick={() => handleTestService(service.name)}
                            disabled={
                              testingService === service.name ||
                              !service.enabled
                            }
                            aria-label={`${testingService === service.name ? "Testing" : "Test"} ${service.name}`}
                          >
                            {testingService === service.name ? (
                              <>
                                <Spinner
                                  animation="border"
                                  size="sm"
                                  className="me-1"
                                />
                                Testing...
                              </>
                            ) : (
                              "Test"
                            )}
                          </Button>
                          <Button
                            variant="outline-secondary"
                            size="sm"
                            className="me-2"
                            onClick={() => handleOpenModal(service)}
                            aria-label={`Edit ${service.name}`}
                          >
                            Edit
                          </Button>
                          <Button
                            variant="outline-danger"
                            size="sm"
                            onClick={() => handleDeleteService(service.name)}
                            disabled={saving}
                            aria-label={`Delete ${service.name}`}
                          >
                            Delete
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Modal
        show={showModal}
        onHide={handleCloseModal}
        size="lg"
        aria-labelledby={modalTitleId}
      >
        <Modal.Header closeButton>
          <Modal.Title id={modalTitleId}>
            {editingService
              ? "Edit Notification Service"
              : "Add Notification Service"}
          </Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {modalAlert && (
            <Alert
              variant={modalAlert.variant}
              dismissible
              onClose={() => setModalAlert(null)}
            >
              {modalAlert.message}
            </Alert>
          )}
          <Form>
            <Form.Group controlId={controlId("service-name")} className="mb-3">
              <Form.Label>Service Name *</Form.Label>
              <Form.Control
                type="text"
                value={formData.name}
                onChange={(e) =>
                  setFormData({ ...formData, name: e.target.value })
                }
                placeholder="My notification service"
                required
                disabled={!!editingService}
              />
              <Form.Text className="text-muted">
                A unique name to identify this service
              </Form.Text>
            </Form.Group>

            <Form.Group controlId={controlId("service-type")} className="mb-3">
              <Form.Label>Service Type *</Form.Label>
              <Form.Select
                value={formData.type}
                onChange={(e) =>
                  setFormData({ ...formData, type: e.target.value })
                }
                disabled={!!editingService}
              >
                {serviceTypes.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </Form.Select>
            </Form.Group>

            <Form.Group
              controlId={controlId("service-enabled")}
              className="mb-3"
            >
              <Form.Check
                type="switch"
                label="Enabled"
                checked={formData.enabled}
                onChange={(e) =>
                  setFormData({ ...formData, enabled: e.target.checked })
                }
              />
            </Form.Group>

            <hr />

            {renderServiceFields()}
          </Form>
        </Modal.Body>
        <Modal.Footer>
          <Button
            variant="primary"
            className="me-auto"
            onClick={handleTestForm}
            disabled={saving || testingForm || !isServiceFormValid(formData)}
          >
            {testingForm ? (
              <>
                <Spinner animation="border" size="sm" className="me-2" />
                Testing...
              </>
            ) : (
              "Test"
            )}
          </Button>
          <Button variant="secondary" onClick={handleCloseModal}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSaveService}
            disabled={saving || testingForm || !isServiceFormValid(formData)}
          >
            {saving ? (
              <>
                <Spinner animation="border" size="sm" className="me-2" />
                Saving...
              </>
            ) : editingService ? (
              "Update Service"
            ) : (
              "Add Service"
            )}
          </Button>
        </Modal.Footer>
      </Modal>
    </Container>
  );
}

export default NotificationsPage;
