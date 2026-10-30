import React, { useEffect, useState } from "react";
import { Alert, Button, Modal, Select, Spin, Tag } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { request } from "../configuration/api.ts";
import { usePageInstance } from "../page-instance.ts";

type LocalNodeRelease = { success: boolean; authorized: boolean; available: boolean; platform: string; version?: string; size_bytes?: number; sha256?: string; download_url?: string; reason?: string };
const PLATFORMS = ["macos-arm64", "windows-x86_64", "linux-x86_64"];

function hostPlatform(): string {
  const ua = navigator.userAgent.toLowerCase();
  if (ua.includes("windows")) return "windows-x86_64";
  if (ua.includes("mac")) return "macos-arm64";
  return "linux-x86_64";
}

export function LocalNodeAccess(): React.ReactElement {
  const { t } = useTranslation();
  const instance = usePageInstance();
  const [open, setOpen] = useState(false);
  const [platform, setPlatform] = useState(hostPlatform);
  const [result, setResult] = useState<LocalNodeRelease | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setLoading(true); setError(""); setResult(null);
    void request(`/api/local-node/releases?platform=${encodeURIComponent(platform)}`, { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) setResult(value);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason?.status === 403 ? t("localNode.permissionDenied") : reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, platform, revision, t]);

  const size = result?.size_bytes ? new Intl.NumberFormat(undefined, { style: "unit", unit: "megabyte", maximumFractionDigits: 0 }).format(result.size_bytes / 1024 / 1024) : "";
  if (instance.mobile) return <></>;
  return <>
    <Button className="tr-local-node-entry" icon={<DownloadOutlined />} onClick={() => setOpen(true)}>{t("localNode.open")}</Button>
    <Modal open={open} onCancel={() => setOpen(false)} footer={null} title={t("localNode.title")} width={560} destroyOnHidden>
      <div className="tr-local-node-panel">
        <p>{t("localNode.scope")}</p>
        <label className="tr-local-node-platform-label" htmlFor="tr-local-node-platform">{t("localNode.platform")}</label>
        <Select id="tr-local-node-platform" value={platform} onChange={setPlatform} options={PLATFORMS.map(value => ({ value, label: t(`localNode.platforms.${value}`) }))} />
        {error ? <Alert type="error" showIcon message={error} action={<Button onClick={() => setRevision(value => value + 1)}>{t("retry")}</Button>} /> : null}
        <Spin spinning={loading}>
          {!loading && result?.authorized && result.available ? <div className="tr-local-node-release">
            <div className="tr-local-node-release-head"><strong>{t("localNode.runtimePackage")}</strong><Tag color="green">{result.version}</Tag></div>
            <p>{t("localNode.packageDescription")}</p>
            <dl><dt>{t("localNode.packageSize")}</dt><dd>{size}</dd><dt>SHA-256</dt><dd className="tr-local-node-hash">{result.sha256}</dd></dl>
            <Button type="primary" icon={<DownloadOutlined />} href={result.download_url}>{t("localNode.download")}</Button>
          </div> : null}
          {!loading && result && !result.available ? <Alert type="info" showIcon message={t("localNode.notPublished")} description={t("localNode.notPublishedHint")} /> : null}
        </Spin>
        <small>{t("localNode.managerBoundary")}</small>
      </div>
    </Modal>
  </>;
}
