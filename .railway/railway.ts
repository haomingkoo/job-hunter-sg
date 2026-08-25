import { defineRailway, github, postgres, preserve, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const repository = github("haomingkoo/job-hunter-sg", { checkSuites: true });

  const Postgres = postgres("Postgres", { region: "asia-southeast1-eqsg3a" });
  const postgresVolume = volume("postgres-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "asia-southeast1-eqsg3a", sizeMB: 5000 });
  const jobAlertsDaily = service("job-alerts-daily", {
    source: repository,
    build: { buildEnvironment: "V3", builder: "DOCKERFILE", dockerfilePath: "Dockerfile.alerts" },
    start: "python send_job_alerts.py",
    replicas: { "asia-southeast1-eqsg3a": 1 },
    deploy: { cronSchedule: "0 23 * * *", restartPolicyType: "NEVER" },
    env: {
      ALERT_UNSUBSCRIBE_SECRET: preserve(),
      APP_BASE_URL: preserve(),
      DATABASE_URL: preserve(),
      JWT_SECRET: preserve(),
      SMTP_FROM_EMAIL: preserve(),
      SMTP_FROM_NAME: preserve(),
      SMTP_HOST: preserve(),
      SMTP_PASSWORD: preserve(),
      SMTP_PORT: preserve(),
      SMTP_USERNAME: preserve(),
      SMTP_USE_SSL: preserve(),
      SMTP_USE_TLS: preserve(),
    },
  });
  const jobHunterSg = service("job-hunter-sg", {
    source: repository,
    replicas: { "asia-southeast1-eqsg3a": 1 },
    domains: ["job.kooexperience.com", "jobhunter.kooexperience.com"],
    env: {
      ACCOUNT_AI_PER_DAY: preserve(),
      ADMIN_API_KEY: preserve(),
      ADMIN_EMAIL: preserve(),
      ADMIN_PASSWORD: preserve(),
      ALLOWED_EMAIL_DOMAINS: preserve(),
      ALLOWED_ORIGINS: preserve(),
      APP_BASE_URL: preserve(),
      APP_ENV: preserve(),
      AUTH_MODE: preserve(),
      CONTACT_EMAIL: preserve(),
      DATABASE_URL: preserve(),
      JWT_SECRET: preserve(),
      LANGCHAIN_API_KEY: preserve(),
      LANGCHAIN_PROJECT: preserve(),
      LANGCHAIN_TRACING_V2: preserve(),
      LANGSMITH_HIDE_INPUTS: preserve(),
      LANGSMITH_HIDE_OUTPUTS: preserve(),
      PRO_EMAIL_DOMAINS: preserve(),
      SEALION_API: preserve(),
      SEALION_API2: preserve(),
      SEALION_API3: preserve(),
      SEALION_API4: preserve(),
      SEALION_API5: preserve(),
      SEALION_API_KEYS: preserve(),
      SKILLSFUTURE_CLIENTID: preserve(),
      SKILLSFUTURE_SECRET: preserve(),
      SMTP_FROM_EMAIL: preserve(),
      SMTP_FROM_NAME: preserve(),
      SMTP_HOST: preserve(),
      SMTP_PASSWORD: preserve(),
      SMTP_PORT: preserve(),
      SMTP_USERNAME: preserve(),
      SMTP_USE_SSL: preserve(),
      SMTP_USE_TLS: preserve(),
      TRUST_CLOUDFLARE_IP_HEADER: preserve(),
    },
  });
  const enthusiasticGratitude = service("enthusiastic-gratitude", {
    source: repository,
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile.crawler" },
    replicas: { "asia-southeast1-eqsg3a": 1 },
    deploy: { cronSchedule: "0 22 * * *", restartPolicyType: "NEVER" },
    env: {
      DATABASE_URL: Postgres.env.DATABASE_URL,
    },
  });

  return project("victorious-rejoicing", {
    resources: [Postgres, jobAlertsDaily, jobHunterSg, enthusiasticGratitude, postgresVolume],
  });
});
