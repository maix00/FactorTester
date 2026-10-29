import React, { useCallback, useEffect, useState } from "react";
import { Alert, Button, Empty, Input, Select, Spin, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";

type Permission = {
  subject: string;
  resource_ref: string;
  scope: string;
  effect: "allow" | "deny";
  created_by: string;
  reason: string;
};

type AuditEntry = {
  subject: string;
  old_effect: string;
  new_effect: string;
  actor: string;
  reason: string;
  changed_at: number;
};

export function PermissionsSettings(): React.ReactElement {
  const { t, i18n } = useTranslation();
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [subject, setSubject] = useState("");
  const [effect, setEffect] = useState<Permission["effect"] | "remove">("allow");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError("");
    try {
      const value = await request("/api/admin/agent-permissions", { signal });
      if (!signal?.aborted) {
        setPermissions(Array.isArray(value.permissions) ? value.permissions : []);
        setAudit(Array.isArray(value.audit) ? value.audit : []);
      }
    } catch (cause) {
      if (!signal?.aborted) {
        setError(cause instanceof Error ? cause.message : t("agentPermissions.loadFailed"));
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const save = async (): Promise<void> => {
    const normalizedSubject = subject.trim();
    const normalizedReason = reason.trim();
    if (!normalizedSubject) { setError(t("agentPermissions.subjectRequired")); return; }
    if (!normalizedReason) { setError(t("agentPermissions.reasonRequired")); return; }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await request("/api/admin/agent-permissions", {
        method: "POST",
        body: JSON.stringify({ subject: normalizedSubject, effect, reason: normalizedReason }),
      });
      setSubject("");
      setReason("");
      setNotice(t(effect === "remove" ? "agentPermissions.removed" : "agentPermissions.saved"));
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("agentPermissions.updateFailed"));
    } finally {
      setSaving(false);
    }
  };

  const permissionColumns: ColumnsType<Permission> = [
    { title: t("agentPermissions.subject"), dataIndex: "subject", key: "subject" },
    {
      title: t("agentPermissions.effect"), dataIndex: "effect", key: "effect",
      render: (value: Permission["effect"]) => value === "allow"
        ? t("agentPermissions.allow") : t("agentPermissions.deny"),
    },
    { title: t("agentPermissions.actor"), dataIndex: "created_by", key: "created_by" },
    { title: t("agentPermissions.reason"), dataIndex: "reason", key: "reason" },
  ];
  const auditColumns: ColumnsType<AuditEntry> = [
    { title: t("agentPermissions.subject"), dataIndex: "subject", key: "subject" },
    {
      title: t("agentPermissions.previous"), dataIndex: "old_effect", key: "old_effect",
      render: (value: string) => !value ? "—" : value === "allow"
        ? t("agentPermissions.allow") : t("agentPermissions.deny"),
    },
    {
      title: t("agentPermissions.current"), dataIndex: "new_effect", key: "new_effect",
      render: (value: string) => !value ? t("agentPermissions.removed")
        : value === "allow" ? t("agentPermissions.allow") : t("agentPermissions.deny"),
    },
    { title: t("agentPermissions.actor"), dataIndex: "actor", key: "actor" },
    {
      title: t("agentPermissions.changedAt"), dataIndex: "changed_at", key: "changed_at",
      render: (value: number) => new Intl.DateTimeFormat(i18n.language, {
        dateStyle: "medium", timeStyle: "short",
      }).format(new Date(value * 1000)),
    },
    { title: t("agentPermissions.reason"), dataIndex: "reason", key: "reason" },
  ];

  return <div className="tr-settings-card tr-agent-permission-settings">
    <Typography.Paragraph type="secondary">{t("permissions.overview")}</Typography.Paragraph>
    {error ? <Alert type="error" showIcon message={error} className="tr-settings-alert" /> : null}
    {notice ? <Alert type="success" showIcon message={notice} className="tr-settings-alert" /> : null}
    <Typography.Paragraph type="secondary">{t("agentPermissions.hint")}</Typography.Paragraph>
    <div className="tr-agent-permission-form">
      <label>
        <span>{t("agentPermissions.subject")}</span>
        <Input value={subject} onChange={event => setSubject(event.target.value)}
          placeholder={t("agentPermissions.subjectHint")} maxLength={306} autoComplete="off" />
      </label>
      <label>
        <span>{t("agentPermissions.effect")}</span>
        <Select value={effect} onChange={setEffect} options={[
          { value: "allow", label: t("agentPermissions.allow") },
          { value: "deny", label: t("agentPermissions.deny") },
          { value: "remove", label: t("agentPermissions.remove") },
        ]} />
      </label>
      <label>
        <span>{t("agentPermissions.reason")}</span>
        <Input value={reason} onChange={event => setReason(event.target.value)}
          placeholder={t("agentPermissions.reasonHint")} maxLength={500} />
      </label>
      <Button type="primary" loading={saving} onClick={() => void save()}>
        {saving ? t("agentPermissions.saving") : effect === "remove"
          ? t("agentPermissions.remove") : t("agentPermissions.save")}
      </Button>
    </div>
    <section className="tr-agent-permission-list" aria-label={t("permissions.assistantUse")}>
      <h3>{t("permissions.assistantUse")}</h3>
      {loading ? <Spin /> : permissions.length ? <Table<Permission>
        size="small" rowKey={item => `${item.subject}:${item.resource_ref}:${item.scope}`} columns={permissionColumns}
        dataSource={permissions} pagination={false} scroll={{ x: true }} /> : <Empty description={t("agentPermissions.empty")} />}
    </section>
    {audit.length ? <section className="tr-agent-permission-list">
      <h3>{t("agentPermissions.history")}</h3>
      <Table<AuditEntry> size="small"
        rowKey={(item, index) => String(index) + ":" + item.subject + ":" + item.changed_at}
        columns={auditColumns} dataSource={audit} pagination={false} scroll={{ x: true }} />
    </section> : null}
  </div>;
}
