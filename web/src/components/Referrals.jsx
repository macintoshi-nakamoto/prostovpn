import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useI18n } from "../lib/i18n/index.jsx";
import "./referrals.css";

export function Referrals() {
  const { t, f } = useI18n();
  const [data, setData] = useState(null);

  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [copied, setCopied] = useState("");

  useEffect(() => {
    let alive = true;
    api
      .referrals()
      .then((body) => alive && setData(body))
      .catch((err) =>
        alive && setError(err instanceof ApiError ? err.message : t("account.refFailed")),
      );
    return () => {
      alive = false;
    };
  }, []);

  const copy = async (kind, value) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(kind);
      setNotice("");
      setTimeout(() => setCopied(""), 1600);
    } catch {
      setNotice(t("account.refCopyFailed"));
    }
  };

  if (error) return <p className="ac-ios-error rf-alone">{error}</p>;
  if (!data) return <p className="ac-empty rf-alone">{t("account.refLoading")}</p>;

  const share = (url) =>
    "https://t.me/share/url?url=" +
    encodeURIComponent(url) +
    "&text=" +
    encodeURIComponent(t("account.refShareText"));

  return (
    <div className="rf">
      {notice && <p className="ac-ios-error rf-notice">{notice}</p>}

      <div className="ac-card rf-hero">
        <span className="rf-days">{f.days(data.days_total)}</span>
        <span className="rf-days-note">{t("account.refDaysEarned")}</span>
        <p className="rf-terms">
          {t("account.refTerms", { join: data.join_days, purchase: data.purchase_days })}
        </p>
      </div>

      <div className="ac-card">
        <div className="ac-card-head">
          <h2>{t("account.refSiteTitle")}</h2>
        </div>
        <p className="rf-sub">{t("account.refSiteSub")}</p>

        <code className="rf-link">{data.site_url}</code>

        <div className="rf-acts">
          <button className="btn btn-primary" onClick={() => copy("site", data.site_url)}>
            {copied === "site" ? t("account.iosCopied") : t("account.refCopy")}
          </button>
          <a
            className="btn btn-outline"
            href={share(data.site_url)}
            target="_blank"
            rel="noreferrer"
          >
            {t("account.refShare")}
          </a>
        </div>
      </div>

      <div className="ac-card">
        <div className="ac-card-head">
          <h2>{t("account.refTgTitle")}</h2>
        </div>

        {data.linked ? (
          <>
            <p className="rf-sub">{t("account.refTgSub")}</p>
            <code className="rf-link">{data.invite_url}</code>
            <div className="rf-acts">
              <button
                className="btn btn-outline"
                onClick={() => copy("bot", data.invite_url)}
              >
                {copied === "bot" ? t("account.iosCopied") : t("account.refCopy")}
              </button>
            </div>
          </>
        ) : (

          <>
            <p className="rf-sub">{t("account.refTgMissing")}</p>
            <a className="btn btn-outline" href={data.bot_url} target="_blank" rel="noreferrer">
              {t("account.refOpenBot")}
            </a>
          </>
        )}
      </div>

      <div className="ac-card">
        <div className="ac-card-head">
          <h2>{t("account.refFriendsTitle")}</h2>
          <span className="ac-ios-count">{data.invited}</span>
        </div>

        <div className="rf-stats">
          <Stat value={data.invited} label={t("account.refStatInvited")} />
          <Stat value={data.purchased} label={t("account.refStatPaid")} />
          {data.pending > 0 && (
            <Stat value={data.pending} label={t("account.refStatPending")} />
          )}
        </div>

        {data.friends.length === 0 ? (
          <p className="ac-empty">{t("account.refEmpty")}</p>
        ) : (
          <div className="rf-list">
            {data.friends.map((friend, index) => (
              <div className="rf-row" key={friend.joined_at + ":" + index}>
                <span className="rf-row-body">
                  <span className="rf-row-name">
                    {t("account.refFriend", { n: data.friends.length - index })}
                  </span>
                  <span className="rf-row-date">
                    {t("account.refCame", { date: f.shortDate(friend.joined_at) })}
                    {friend.paid ? " · " + t("account.refPaid") : ""}
                  </span>
                </span>
                <span className={"rf-row-days" + (friend.pending ? " is-waiting" : "")}>
                  {friend.pending ? t("account.refWaiting") : "+" + f.days(friend.days)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ value, label }) {
  return (
    <span className="rf-stat">
      <span className="rf-stat-value">{value}</span>
      <span className="rf-stat-label">{label}</span>
    </span>
  );
}
