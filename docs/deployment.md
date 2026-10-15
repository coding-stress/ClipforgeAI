# Hosted HTTPS deployment and social setup

ClipforgeAI is configured as a single-workspace hosted app. The repository includes a Docker image and a Render blueprint with a persistent disk. Keep one running web instance: it owns the scheduler and the SQLite social-account and post queue databases.

## 1. Deploy the app

1. Push this repository to a private GitHub repository and create a Render service from `render.yaml`.
2. Keep the persistent disk mounted at `/app/backend/data`; it stores projects, videos, OAuth tokens, and scheduled posts. Back up this disk and set a retention policy for old video files.
3. After Render assigns the HTTPS hostname, set `APP_BASE_URL` to that exact origin, such as `https://clipforgeai.onrender.com`.
4. In Render’s secret environment variables, set a strong `APP_PASSWORD`, `APP_SESSION_SECRET`, `MEDIA_SIGNING_KEY`, and `TOKEN_ENCRYPTION_KEY`. Generate the random keys from the backend virtual environment:

   ```powershell
   .venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
   .venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   Use the first command for each signing secret. Use the Fernet command for `TOKEN_ENCRYPTION_KEY`. Save these secrets outside the repository. If the encryption key is lost, existing social tokens cannot be recovered; reconnect the accounts.

5. Add your OpenAI API key as `OPENAI_API_KEY` if using Best Parts or AI subtitles.
6. Redeploy after environment variables are set, then sign in with `APP_PASSWORD`.

## 2. Register provider OAuth apps

Use these exact callback URLs in each developer console after `APP_BASE_URL` is set:

| Provider | Callback URL | Main requirements |
| --- | --- | --- |
| YouTube | `${APP_BASE_URL}/api/social/youtube/callback` | Google OAuth web client; enable YouTube Data API v3; request `youtube.upload`. Google may require OAuth verification and YouTube API audit before public uploads. |
| Instagram | `${APP_BASE_URL}/api/social/instagram/callback` | Meta app; professional Instagram account linked to a Facebook Page; `instagram_basic`, `instagram_content_publish`, `pages_show_list`, and `pages_read_engagement`. Public Reels need Instagram’s server to fetch the temporary signed HTTPS video URL. |
| Facebook | `${APP_BASE_URL}/api/social/facebook/callback` | Meta app and a Facebook Page with publishing permission; `pages_show_list`, `pages_read_engagement`, and `pages_manage_posts`. |
| TikTok | `${APP_BASE_URL}/api/social/tiktok/callback` | TikTok Login Kit and Content Posting API product; approve `video.publish`. Unaudited apps are restricted to private posts until TikTok audits the app. |
| X | `${APP_BASE_URL}/api/social/x/callback` | X OAuth 2.0 user authorization with `tweet.read`, `users.read`, `tweet.write`, `media.write`, and `offline.access`; enable the video upload and posting API access in your X developer project. |
| LinkedIn | `${APP_BASE_URL}/api/social/linkedin/callback` | LinkedIn OAuth app with OpenID Connect and `w_member_social`; video posting must also have the required Community Management API access. |

Put provider client IDs and secrets in the matching Render environment variables listed in `backend/.env.example`. Instagram and Facebook share `META_CLIENT_ID` and `META_CLIENT_SECRET`. Never put provider secrets in frontend code or commit them.

After connecting, confirm the intended account appears in **Publishing settings**. Generate vertical clips, preview the post, select accounts, set a cadence, and schedule. Scheduled entries appear in the publishing queue with their processing result. Failed jobs show the provider response so you can correct permissions, account eligibility, or video constraints and schedule again.

## 3. Current provider constraints

- Provider developer approval is external to this project. A connected OAuth account does not guarantee the platform has approved public publishing.
- Instagram requires a public HTTPS video URL it can fetch. ClipforgeAI creates a signed URL that expires after 24 hours when the scheduled post is due.
- TikTok’s public posting depends on approved scopes and an audited app. Until then, TikTok may limit visibility to private/self-only.
- X access levels and upload limits depend on the developer account plan.
- LinkedIn posting uses the current API version configured by `LINKEDIN_VERSION`; update it as LinkedIn releases and sunsets monthly versions.
- One scheduled cadence is shared across the clips in a project: every six hours or every day. Platform outages or expired/revoked tokens can cause a post to fail; review the queue and reconnect the affected account.
- The app is single-workspace. Do not expose it to multiple unrelated customers without adding tenant accounts, authorization, quotas, and per-user storage isolation.
