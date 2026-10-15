# Hosted HTTPS deployment and social setup

ClipforgeAI is configured as a single-workspace app. The included Render blueprint targets a free prototype in Singapore. Render provides HTTPS and generates the session, media-signing, and token-encryption keys. Its free web service sleeps after 15 minutes without incoming traffic and has an ephemeral filesystem. Uploaded videos, clips, project records, connected account tokens, and scheduled posts can disappear when it sleeps, restarts, or redeploys. Scheduled publishing only runs while the service is awake, so treat it as a demo and do not rely on it for time-sensitive posts. Render has monthly usage limits; without a payment method it may suspend the service when a free quota is exhausted. With a payment method, usage beyond free allowances can incur charges, so set a spend limit.

## 1. Deploy the app

1. In Render, choose **New → Blueprint**, connect the GitHub repository, and use `render.yaml` on `main`. Confirm the service plan is **Free** and there is no disk attached before deploying.
2. Set a private `APP_PASSWORD` with at least 12 characters. Render generates the session, media-signing, and token-encryption keys for the service.
3. Set `OPENAI_API_KEY` if you want Best Parts or AI subtitles. OpenAI API usage may incur charges; Sequence Wise works without it.
4. After Render assigns the HTTPS hostname, the app uses Render's `RENDER_EXTERNAL_URL` automatically for secure cookies, social OAuth callbacks, and Instagram's signed media links. If you use a custom HTTPS domain later, set `APP_BASE_URL` to that origin.

## 2. Register provider OAuth apps

To connect a social provider, add its OAuth client credentials to the service's **Environment** settings, then enter `https://YOUR-SERVICE.onrender.com/api/social/PROVIDER/callback` in that provider's developer console. Keep API secrets in Render's secret settings, never in frontend code or Git. Register these callbacks:

| Provider | Callback URL | Main requirements |
| --- | --- | --- |
| YouTube | `https://YOUR-SERVICE.onrender.com/api/social/youtube/callback` | Google OAuth web client; enable YouTube Data API v3; request `youtube.upload`. Google may require OAuth verification and YouTube API audit before public uploads. |
| Instagram | `https://YOUR-SERVICE.onrender.com/api/social/instagram/callback` | Meta app; professional Instagram account linked to a Facebook Page; `instagram_basic`, `instagram_content_publish`, `pages_show_list`, and `pages_read_engagement`. Public Reels need Instagram’s server to fetch the temporary signed HTTPS video URL. |
| Facebook | `https://YOUR-SERVICE.onrender.com/api/social/facebook/callback` | Meta app and a Facebook Page with publishing permission; `pages_show_list`, `pages_read_engagement`, and `pages_manage_posts`. |
| TikTok | `https://YOUR-SERVICE.onrender.com/api/social/tiktok/callback` | TikTok Login Kit and Content Posting API product; approve `video.publish`. Unaudited apps are restricted to private posts until TikTok audits the app. |
| X | `https://YOUR-SERVICE.onrender.com/api/social/x/callback` | X OAuth 2.0 user authorization with `tweet.read`, `users.read`, `tweet.write`, `media.write`, and `offline.access`; enable the video upload and posting API access in your X developer project. |
| LinkedIn | `https://YOUR-SERVICE.onrender.com/api/social/linkedin/callback` | LinkedIn OAuth app with OpenID Connect and `w_member_social`; video posting must also have the required Community Management API access. |

Put provider client IDs and secrets in the matching Render environment variables listed in `backend/.env.example`. Instagram and Facebook share `META_CLIENT_ID` and `META_CLIENT_SECRET`. Never put provider secrets in frontend code or commit them.

After connecting, confirm the intended account appears in **Publishing settings**. Generate vertical clips, preview the post, select accounts, set a cadence, and schedule. Scheduled entries appear in the publishing queue with their processing result. On this free prototype, queue state and account connections may disappear after the service sleeps or restarts.

## 3. Current provider constraints

- Provider developer approval is external to this project. A connected OAuth account does not guarantee the platform has approved public publishing.
- Instagram requires a public HTTPS video URL it can fetch. ClipforgeAI creates a signed URL that expires after 24 hours when the scheduled post is due.
- TikTok’s public posting depends on approved scopes and an audited app. Until then, TikTok may limit visibility to private/self-only.
- X access levels and upload limits depend on the developer account plan.
- LinkedIn posting uses the current API version configured by `LINKEDIN_VERSION`; update it as LinkedIn releases and sunsets monthly versions.
- One scheduled cadence is shared across the clips in a project: every six hours or every day. Platform outages or expired/revoked tokens can cause a post to fail; review the queue and reconnect the affected account.
- The app is single-workspace. Do not expose it to multiple unrelated customers without adding tenant accounts, authorization, quotas, and per-user storage isolation.

## Moving to reliable hosting

For persistent projects and dependable scheduling, use a continuously running paid service with persistent storage, or move media and queue data to durable managed services. Back up stored videos and the database. Keep one backend worker to own the scheduler and SQLite queue. Generate signing secrets locally with `secrets.token_urlsafe(48)` and generate `TOKEN_ENCRYPTION_KEY` with `Fernet.generate_key()`; save them in the host's secret manager. If the token encryption key is lost, reconnect the social accounts.
