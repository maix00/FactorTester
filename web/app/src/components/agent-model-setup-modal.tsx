import React, { useEffect, useState } from "react";
import { Alert, Button, Form, Input, Modal, Select, Space } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";

type ProtocolDetail = { protocol: string; label?: string };
type RuntimeCapability = {
  runtime: string;
  executable_label?: string;
  protocols?: string[];
  protocol_details?: ProtocolDetail[];
  network_route_details?: Array<{ network_route: string; label: string }>;
};
type Provider = { provider_id: string };
type ProviderDraft = {
  label: string;
  agent_runtime: string;
  protocol: string;
  base_url: string;
  default_model: string;
  network_route: string;
  token: string;
};

export function AgentModelSetupModal({
  open,
  onCancel,
  onSaved,
  capabilities,
}: {
  open: boolean;
  onCancel: () => void;
  onSaved: (providerID: string) => void;
  capabilities: RuntimeCapability[];
}): React.ReactElement {
  const { t } = useTranslation();
  const [form] = Form.useForm<ProviderDraft>();
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [error, setError] = useState("");
  const runtime = Form.useWatch("agent_runtime", form);
  const selectedCapability = capabilities.find((item) => item.runtime === runtime) || capabilities[0];
  const protocols = selectedCapability?.protocols || [];
  const networkRoutes = selectedCapability?.network_route_details || [];

  useEffect(() => {
    if (!open) return;
    const initialCapability = capabilities[0];
    form.setFieldsValue({
      label: "",
      agent_runtime: initialCapability?.runtime || "codex",
      protocol: initialCapability?.protocols?.includes("openai_responses")
        ? "openai_responses" : initialCapability?.protocols?.[0] || "openai_responses",
      base_url: "",
      default_model: "",
      network_route: "direct",
      token: "",
    });
    setTestResult(null);
    setError("");
  }, [capabilities, form, open]);

  useEffect(() => {
    if (!open || !selectedCapability || protocols.length === 0) return;
    const current = form.getFieldValue("protocol");
    if (protocols.includes(current)) return;
    form.setFieldValue("protocol", protocols.includes("openai_responses") ? "openai_responses" : protocols[0]);
  }, [form, open, protocols, selectedCapability]);

  const payload = (values: ProviderDraft) => ({
    label: values.label.trim(),
    runtime_kind: "server",
    agent_runtime: values.agent_runtime,
    protocol: values.protocol,
    base_url: values.base_url.trim(),
    default_model: values.default_model.trim(),
    network_route: values.network_route || "direct",
    token: values.token,
  });

  const testConnection = async (): Promise<void> => {
    setError("");
    setTestResult(null);
    let values: ProviderDraft;
    try { values = await form.validateFields(); }
    catch { return; }
    setTesting(true);
    try {
      const result = await request("/api/client/agent-models/test", {
        method: "POST", body: JSON.stringify(payload(values)),
      });
      const tested = result.test || {};
      const details = [tested.default_model, Number.isFinite(tested.latency_ms) ? `${tested.latency_ms} ms` : ""]
        .filter(Boolean).join(" · ");
      setTestResult({ type: "success", text: details ? `${t("assistant.connectionSuccess")} · ${details}` : t("assistant.connectionSuccess") });
    } catch (cause) {
      setTestResult({ type: "error", text: cause instanceof Error ? cause.message : String(cause) });
    } finally { setTesting(false); }
  };

  const save = async (values: ProviderDraft): Promise<void> => {
    setSaving(true);
    setError("");
    try {
      const result = await request("/api/client/agent-models", {
        method: "POST", body: JSON.stringify(payload(values)),
      });
      const provider = result.provider as Provider | undefined;
      if (!provider?.provider_id) throw new Error(t("assistant.modelSaveFailed"));
      onSaved(provider.provider_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally { setSaving(false); }
  };

  return <Modal
    open={open}
    title={t("assistant.modelAddTitle")}
    onCancel={onCancel}
    footer={null}
    centered
    width={560}
    destroyOnHidden
    className="tr-agent-model-setup-modal"
  >
    <Form form={form} layout="vertical" onFinish={(values) => void save(values)}>
      <Form.Item name="label" label={t("assistant.modelName")} rules={[{ required: true }]}>
        <Input maxLength={120} autoComplete="off" />
      </Form.Item>
      <Form.Item name="agent_runtime" label={t("assistant.modelRuntime")} rules={[{ required: true }]}>
        <Select options={capabilities.map((item) => ({ value: item.runtime, label: item.executable_label || item.runtime }))} />
      </Form.Item>
      <Form.Item name="protocol" label={t("assistant.modelProtocol")} rules={[{ required: true }]}>
        <Select options={protocols.map((protocol) => ({
          value: protocol,
          label: selectedCapability?.protocol_details?.find((item) => item.protocol === protocol)?.label || protocol,
        }))} />
      </Form.Item>
      <Form.Item name="base_url" label={t("assistant.modelBaseUrl")} rules={[{ required: true, type: "url" }]}>
        <Input placeholder="https://api.example.com/v1" inputMode="url" />
      </Form.Item>
      <Form.Item name="default_model" label={t("assistant.modelDefaultModel")} rules={[{ required: true }]}>
        <Input autoComplete="off" />
      </Form.Item>
      <Form.Item name="token" label={t("assistant.modelToken")} rules={[{ required: true }]}>
        <Input.Password autoComplete="new-password" />
      </Form.Item>
      <Form.Item name="network_route" label={t("assistant.modelNetworkRoute")} rules={[{ required: true }]}>
        <Select options={networkRoutes.map((item) => ({
          value: item.network_route,
          label: t(`assistant.networkRoutes.${item.network_route}`, { defaultValue: item.label }),
        }))} />
      </Form.Item>
      {testResult ? <Alert className="tr-agent-model-test-result" type={testResult.type} showIcon message={testResult.text} /> : null}
      {error ? <Alert className="tr-agent-model-test-result" type="error" showIcon message={error} /> : null}
      <div className="tr-agent-model-setup-actions">
        <Button onClick={() => void testConnection()} loading={testing}>{t("assistant.testModelConnection")}</Button>
        <Space>
          <Button onClick={onCancel}>{t("configuration.cancel")}</Button>
          <Button type="primary" htmlType="submit" loading={saving}>{t("assistant.saveModel")}</Button>
        </Space>
      </div>
    </Form>
  </Modal>;
}
