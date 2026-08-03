"""Classify ATS terms from O*NET, SkillsFuture, and learned job data."""

from __future__ import annotations

import logging

log = logging.getLogger("jobhunter.taxonomy")

ONET_SKILLS: set[str] = {
    "active learning", "active listening", "complex problem solving",
    "coordination", "critical thinking", "equipment maintenance",
    "equipment selection", "installation", "instructing",
    "judgment and decision making", "learning strategies",
    "management of financial resources", "management of material resources",
    "management of personnel resources", "mathematics", "monitoring",
    "negotiation", "operation and control", "operations analysis",
    "operations monitoring", "persuasion", "programming",
    "quality control analysis", "reading comprehension", "repairing",
    "science", "service orientation", "social perceptiveness",
    "speaking", "systems analysis", "systems evaluation",
    "technology design", "time management", "troubleshooting", "writing",
}

# Source: O*NET 29.1 Knowledge.xlsx, Element Name column (all 33 unique values)
ONET_KNOWLEDGE: set[str] = {
    "administration and management", "administrative",
    "biology", "building and construction",
    "chemistry", "communications and media", "computers and electronics",
    "customer and personal service", "design", "economics and accounting",
    "education and training", "engineering and technology",
    "english language", "fine arts", "food production",
    "foreign language", "geography",
    "history and archeology", "law and government", "mathematics",
    "mechanical", "medicine and dentistry", "personnel and human resources",
    "philosophy and theology", "physics", "production and processing",
    "psychology", "public safety and security", "sales and marketing",
    "sociology and anthropology", "telecommunications",
    "therapy and counseling", "transportation",
}

# These are flagged by O*NET as "Hot Technology" -- in high employer demand.
# Stored as lowercased short names for matching (original full names in data/).
ONET_HOT_TECHNOLOGIES: set[str] = {
    "ajax", "adobe acrobat", "adobe after effects", "adobe creative cloud",
    "adobe illustrator", "adobe indesign", "adobe photoshop",
    "alteryx", "amazon dynamodb", "amazon ec2", "amazon redshift",
    "amazon s3", "aws cloudformation", "aws",
    "ansible", "apache cassandra", "apache hadoop", "apache hive",
    "apache kafka", "apache maven", "apache spark",
    "apache subversion", "svn", "apache tomcat",
    "ios", "macos", "atlassian bamboo", "bitbucket", "confluence",
    "jira", "autodesk autocad", "autocad civil 3d", "autodesk revit",
    "bash", "bentley microstation", "bootstrap", "bgp",
    "border gateway protocol",
    "c", "c#", "c++", "canva", "css", "cascading style sheets",
    "chef", "cisco webex", "solidworks",
    "django", "docker", "drupal",
    "arcgis", "esri", "eclipse", "eclipse jersey",
    "elasticsearch", "epic systems",
    "xml", "facebook", "figma",
    "git", "github", "gitlab",
    "go", "golang",
    "google analytics", "android", "angular", "angularjs",
    "google docs", "google sheets", "google workspace",
    "graphql", "henry schein dentrix",
    "hibernate", "hubspot",
    "html", "hypertext markup language",
    "ibm db2", "db2", "ibm spss", "spss",
    "terraform", "ibm websphere mq", "websphere",
    "informatica", "quickbooks",
    "junit", "javascript", "json",
    "jenkins", "kronos", "kubernetes", "k8s",
    "linux", "meditech",
    "marketo", ".net", ".net framework", "asp.net",
    "microsoft access", "active directory", "asp",
    "azure", "microsoft dynamics", "dynamics 365",
    "excel", "microsoft office", "outlook",
    "power bi", "powerpoint", "powershell",
    "microsoft project", "sql server", "ssis", "ssrs",
    "sharepoint", "tfs", "team foundation server",
    "microsoft teams", "teams",
    "visio", "visual basic", "vba", "visual studio",
    "windows", "windows server", "microsoft word",
    "mongodb", "mysql", "nosql",
    "node.js", "nodejs",
    "oracle cloud", "oracle database", "oracle",
    "java", "j2ee", "jsp", "pl/sql",
    "peoplesoft", "primavera", "sql developer",
    "php", "perl", "postgresql", "postgres",
    "procore", "puppet", "python",
    "r", "react", "reactjs",
    "red hat enterprise linux", "rhel", "openshift",
    "redis", "ruby", "ruby on rails", "rails",
    "sap concur", "sap erp", "sap",
    "sas", "salesforce", "scala",
    "selenium", "servicenow",
    "shell script", "shell scripting",
    "slack", "splunk",
    "spring boot", "spring framework", "spring",
    "sql", "structured query language",
    "swift", "tableau", "tensorflow",
    "teradata", "matlab",
    "tiktok", "transact-sql", "t-sql",
    "trimble sketchup", "sketchup",
    "typescript", "unix", "unix shell",
    "vue.js", "vuejs", "vue",
    "wordpress", "workday", "yardi", "zoom",
    "eclinicalworks", "jquery",
}

# Source: Technology Skills.xlsx, Commodity Title column (unique values)
ONET_SOFTWARE_CATEGORIES: set[str] = {
    "access software", "accounting software", "administration software",
    "analytical or scientific software", "application server software",
    "audit software", "authentication server software",
    "backup or archival software", "bar coding software",
    "business intelligence and data analysis software",
    "calendar and scheduling software",
    "categorization or classification software", "charting software",
    "cloud-based data access and sharing software",
    "cloud-based management software",
    "cloud-based protection or security software",
    "clustering software", "communications server software",
    "compiler and decompiler software", "compliance software",
    "computer aided design software", "cad software", "cam software",
    "computer based training software", "computer imaging software",
    "configuration management software", "contact center software",
    "content workflow software",
    "crm software", "customer relationship management software",
    "database management system software",
    "database reporting software",
    "data base user interface and query software",
    "data compression software", "data conversion software",
    "data mining software", "desktop communications software",
    "desktop publishing software", "development environment software",
    "device drivers or system software", "document management software",
    "electronic mail software",
    "enterprise application integration software",
    "enterprise resource planning software", "erp software",
    "enterprise system management software", "expert system software",
    "facilities management software", "file versioning software",
    "filesystem software", "financial analysis software",
    "flight control software", "gateway software",
    "geographic information system", "gis software",
    "graphical user interface development software",
    "gui development software",
    "graphics or photo imaging software",
    "helpdesk or call center software",
    "human resources software", "hr software",
    "industrial control software",
    "information retrieval or search software",
    "instant messaging software", "interactive voice response software",
    "internet browser software", "internet directory services software",
    "inventory management software", "lan software",
    "label making software", "legal management software",
    "library software", "license management software",
    "mailing and shipping software",
    "manufacturing execution system software", "mes software",
    "map creation software",
    "materials requirements planning software", "mrp software",
    "medical software", "metadata management software",
    "mobile location based services software",
    "multi-media educational software",
    "music or sound editing software",
    "network conferencing software", "network monitoring software",
    "network operating system software", "network security software",
    "vpn software", "object oriented development software",
    "office suite software", "operating system software",
    "optical character reader software", "ocr software",
    "pattern design software", "platform interconnectivity software",
    "point of sale software", "pos software",
    "portal server software", "presentation software",
    "procedure management software",
    "process mapping and design software",
    "procurement software", "program testing software",
    "project management software",
    "requirements analysis software", "risk management software",
    "route navigation software", "sales and marketing software",
    "spell checkers", "spreadsheet software",
    "storage networking software", "switch or router software",
    "tax preparation software", "text to speech software",
    "time accounting software", "transaction security software",
    "virus protection software", "transaction server software",
    "video conferencing software",
    "video creation and editing software",
    "voice recognition software", "speech recognition software",
    "web page creation and editing software",
    "web platform development software",
    "wireless software", "word processing software",
}

# Programming languages, frameworks, tools, platforms, methodologies.
# Includes O*NET widely-used technologies (5+ occupations) plus modern tools.
TECH_SKILLS: set[str] = {
    # Programming Languages
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "golang",
    "rust", "ruby", "php", "swift", "kotlin", "scala", "r", "matlab",
    "perl", "haskell", "lua", "dart", "elixir", "clojure", "groovy",
    "objective-c", "assembly", "fortran", "cobol", "abap", "vba",
    "powershell", "bash", "shell scripting", "sql", "plsql", "t-sql",
    "nosql", "graphql", "html", "css", "sass", "less",
    "pascal", "delphi", "ada", "smalltalk", "prolog", "lisp",
    "erlang", "f#", "vbscript", "apex", "solidity",
    # Frontend Frameworks
    "react", "angular", "vue", "svelte", "next.js", "nuxt", "gatsby",
    "remix", "astro", "ember", "backbone", "jquery", "bootstrap",
    "tailwind", "tailwind css", "material ui", "chakra ui", "ant design",
    "ext js",
    # Backend Frameworks
    "node.js", "express", "fastapi", "django", "flask", "spring",
    "spring boot", ".net", ".net core", "asp.net", "rails", "laravel",
    "symfony", "codeigniter",
    "gin", "fiber", "actix", "rocket", "phoenix", "nestjs",
    "deno", "bun", "fastify",
    # Mobile
    "react native", "flutter", "ios", "android", "xamarin", "ionic",
    "swiftui", "jetpack compose", "android sdk",
    # Cloud & Infrastructure
    "aws", "amazon web services", "azure", "microsoft azure",
    "gcp", "google cloud", "google cloud platform",
    "alibaba cloud", "ibm cloud", "oracle cloud",
    "digitalocean", "heroku", "netlify", "vercel", "railway",
    "cloudflare", "akamai",
    "ec2", "amazon ec2", "s3", "amazon s3", "lambda", "aws lambda",
    "ecs", "eks", "fargate", "rds", "dynamodb", "sqs", "sns",
    "sagemaker", "glue", "athena",
    "cloudformation", "aws cloudformation", "cloudwatch",
    "cdk", "sam", "api gateway",
    "azure devops", "azure functions", "azure pipelines", "azure ad",
    "bigquery", "google bigquery", "cloud run", "cloud functions",
    "google kubernetes engine", "gke", "pub/sub",
    "docker", "kubernetes", "k8s", "openshift", "red hat openshift",
    "helm", "kustomize", "istio", "envoy",
    "terraform", "ansible", "puppet", "chef", "saltstack",
    "vagrant", "packer",
    "jenkins", "jenkins ci", "github actions", "gitlab ci",
    "circleci", "travis ci", "bamboo", "atlassian bamboo",
    "teamcity", "argo", "argo cd", "tekton", "spinnaker",
    "nginx", "apache", "apache tomcat", "iis", "caddy", "traefik",
    "linux", "ubuntu", "centos", "debian", "fedora",
    "red hat", "rhel", "red hat enterprise linux",
    "suse", "alpine",
    "unix", "aix", "solaris", "hp-ux",
    "windows", "windows server", "macos",
    "vmware", "hyper-v", "virtualbox", "kvm", "citrix",
    # Databases
    "postgresql", "postgres", "mysql", "mariadb", "oracle", "oracle database",
    "sql server", "microsoft sql server", "mssql",
    "sqlite", "mongodb", "cassandra", "apache cassandra",
    "redis", "memcached",
    "elasticsearch", "opensearch", "solr", "apache solr",
    "neo4j", "neptune", "couchdb", "couchbase",
    "influxdb", "timescaledb", "cockroachdb", "planetscale",
    "supabase", "firebase", "firestore",
    "dynamodb", "amazon dynamodb",
    "db2", "ibm db2", "teradata", "snowflake",
    "redshift", "amazon redshift",
    "hbase", "apache hbase",
    # Data & Analytics
    "spark", "apache spark", "pyspark",
    "hadoop", "apache hadoop", "hive", "apache hive",
    "presto", "trino", "airflow", "apache airflow",
    "dagster", "prefect", "luigi",
    "nifi", "apache nifi",
    "kafka", "apache kafka", "rabbitmq", "pulsar",
    "flink", "apache flink", "storm", "beam",
    "dbt", "fivetran", "airbyte", "talend", "informatica", "stitch",
    "snowflake", "databricks", "redshift", "synapse", "palantir",
    "looker", "metabase", "superset", "grafana", "kibana",
    "tableau", "power bi", "powerbi",
    "qlik", "qlikview", "qliksense", "sisense", "microstrategy",
    "pandas", "numpy", "scipy", "polars", "dask",
    "matplotlib", "seaborn", "plotly", "d3.js", "d3",
    "alteryx", "knime", "rapidminer",
    "sas", "spss", "ibm spss", "stata", "minitab",
    "jupyter", "jupyter notebook", "jupyterlab",
    "crystal reports", "ssrs", "ssis",
    "etl", "elt", "data pipeline", "data warehouse", "data lake",
    "data modeling", "data governance", "data quality",
    "excel", "google sheets",
    # AI / ML
    "machine learning", "deep learning", "natural language processing",
    "nlp", "computer vision", "reinforcement learning",
    "tensorflow", "pytorch", "keras", "scikit-learn", "sklearn",
    "xgboost", "lightgbm", "catboost",
    "hugging face", "huggingface", "transformers",
    "langchain", "llamaindex", "openai", "chatgpt",
    "llm", "large language models", "gpt", "bert",
    "stable diffusion", "midjourney", "dall-e",
    "generative ai", "rag",
    "mlflow", "kubeflow", "sagemaker", "vertex ai", "bedrock",
    "weights and biases", "wandb",
    "feature engineering", "model deployment", "mlops",
    "opencv", "yolo", "mediapipe", "detectron",
    "spacy", "nltk", "gensim",
    "neural networks", "cnn", "rnn", "lstm", "gan",
    # DevOps & SRE
    "ci/cd", "devops", "devsecops", "gitops",
    "sre", "site reliability",
    "monitoring", "observability",
    "prometheus", "datadog", "new relic",
    "splunk", "elk stack", "logstash", "fluentd",
    "nagios", "zabbix", "pagerduty", "opsgenie",
    "consul", "vault",
    "incident management", "infrastructure as code",
    "chaos engineering",
    # Security
    "cybersecurity", "information security", "network security",
    "application security",
    "penetration testing", "vulnerability assessment",
    "siem", "soar", "edr", "xdr", "waf",
    "oauth", "saml", "oidc", "jwt", "ldap", "active directory",
    "okta", "auth0", "ping identity",
    "encryption", "ssl", "tls", "pki", "hashicorp vault",
    "wireshark", "nmap", "metasploit", "burp suite",
    "snort", "nessus", "qualys", "rapid7",
    "crowdstrike", "carbon black", "sentinelone",
    "compliance", "gdpr", "sox", "pci-dss", "iso 27001", "nist",
    # Networking
    "tcp/ip", "dns", "dhcp", "vpn", "sd-wan", "mpls",
    "bgp", "ospf", "ipsec",
    "cisco", "cisco ios", "juniper", "palo alto", "fortinet",
    "checkpoint", "f5",
    "load balancing", "cdn", "cloudflare",
    # Business Software & ERP
    "sap", "sap s/4hana", "sap hana", "sap bw", "sap fi/co",
    "sap mm", "sap sd", "sap pp", "sap abap", "sap basis",
    "sap business one", "sap fiori", "sap concur",
    "oracle erp", "oracle financials", "oracle hcm",
    "oracle peoplesoft", "peoplesoft",
    "salesforce", "salesforce crm", "salesforce lightning",
    "hubspot", "zoho", "zoho crm", "pipedrive",
    "freshworks", "freshdesk", "freshsales",
    "servicenow", "zendesk", "intercom",
    "workday", "successfactors", "peoplesoft",
    "netsuite", "sage", "quickbooks", "xero",
    "microsoft dynamics", "dynamics 365", "dynamics crm",
    "microsoft 365", "sharepoint", "microsoft sharepoint",
    "power platform", "power automate", "power apps", "power bi",
    "outlook", "microsoft outlook",
    "powerpoint", "microsoft powerpoint",
    "word", "microsoft word",
    "access", "microsoft access",
    "visio", "microsoft visio",
    "onenote", "microsoft office",
    "google docs", "google drive", "google workspace",
    "bmc remedy", "adp", "kronos",
    # Project & Product Management
    "jira", "confluence", "trello", "asana", "monday.com",
    "clickup", "notion", "linear", "shortcut",
    "basecamp", "wrike", "smartsheet",
    "microsoft project", "primavera",
    "miro",
    "agile", "scrum", "kanban", "safe", "scaled agile", "lean",
    "waterfall", "prince2", "pmp", "six sigma",
    "product management", "roadmapping", "user stories",
    "sprint planning", "retrospective",
    # Design & UX
    "figma", "sketch", "adobe xd", "invision", "zeplin",
    "photoshop", "adobe photoshop",
    "illustrator", "adobe illustrator",
    "indesign", "adobe indesign",
    "after effects", "adobe after effects",
    "premiere pro", "adobe premiere",
    "creative cloud", "adobe creative cloud",
    "canva", "coreldraw", "blender",
    "autocad", "autodesk autocad", "revit", "autodesk revit",
    "solidworks", "catia", "creo", "inventor",
    "3ds max", "maya", "cinema 4d",
    "sketchup", "rhino", "rhinoceros",
    "ux design", "ui design", "user research",
    "wireframing", "prototyping", "design thinking",
    "accessibility", "wcag", "responsive design",
    # Testing & QA
    "selenium", "cypress", "playwright", "puppeteer",
    "jest", "mocha", "chai", "jasmine",
    "pytest", "junit", "testng", "mockito", "unittest",
    "cucumber", "postman", "swagger", "openapi",
    "gatling", "jmeter", "locust", "k6", "artillery",
    "sonarqube", "codecov", "coveralls",
    "appium", "robot framework",
    "test automation", "manual testing", "regression testing",
    "performance testing", "load testing",
    "api testing", "integration testing", "unit testing",
    # IDEs & Editors
    "visual studio", "visual studio code", "vscode",
    "intellij", "intellij idea", "pycharm", "webstorm",
    "eclipse", "eclipse ide", "netbeans",
    "xcode", "android studio",
    "vim", "neovim", "emacs", "sublime text",
    # Version Control
    "git", "github", "gitlab", "bitbucket", "svn", "subversion",
    "mercurial", "tfs", "team foundation server",
    # Finance & Banking Tech
    "bloomberg", "bloomberg terminal", "reuters", "refinitiv",
    "murex", "calypso", "summit",
    "finacle", "temenos", "fis", "finastra",
    "swift messaging", "iso 20022", "fix protocol",
    "kyc", "aml", "cft", "sanctions screening",
    "risk modeling", "var", "credit risk", "market risk",
    "algorithmic trading", "quantitative analysis",
    "financial modeling", "dcf", "lbo",
    "ifrs", "gaap", "us gaap",
    # Healthcare Tech
    "epic", "epic systems", "cerner", "meditech",
    "hl7", "fhir", "dicom", "pacs",
    "electronic health records", "ehr", "emr",
    "clinical trials", "pharmacovigilance", "gmp", "gcp",
    "icd-10", "cpt coding", "medical coding",
    "henry schein dentrix",
    # Manufacturing & Engineering
    "autocad", "solidworks", "catia", "siemens nx",
    "siemens solid edge", "ptc creo",
    "ansys", "comsol", "abaqus",
    "matlab", "simulink", "labview", "national instruments labview",
    "plc", "plc programming", "scada", "dcs", "mes", "erp",
    "lean manufacturing", "tpm", "oee",
    "iso 9001", "iso 14001", "iso 45001",
    "fmea", "spc", "8d", "kaizen", "5s",
    "supply chain management", "demand planning",
    "inventory optimization", "mrp",
    "cnc", "cnc machining", "cnc programming",
    "gd&t", "bim", "building information modeling",
    "semiconductor", "lithography", "metrology",
    "wafer fabrication", "yield engineering",
    "3d printing", "additive manufacturing",
    "pcb design", "circuit design",
    "vlsi", "fpga", "asic",
    "microstation", "bentley microstation",
    "procore", "yardi",
    # GIS & Geospatial
    "arcgis", "esri arcgis", "qgis",
    "google earth", "gis",
    # Scientific & Statistical
    "sas", "spss", "stata", "minitab", "eviews",
    "wolfram mathematica",
    "r", "rstudio",
    # Marketing & Analytics
    "google analytics", "ga4", "google tag manager", "gtm",
    "google ads", "facebook ads", "meta ads", "linkedin ads",
    "seo", "sem", "ppc", "cro",
    "mailchimp", "sendgrid", "marketo", "pardot",
    "segment", "amplitude", "mixpanel", "heap",
    "a/b testing", "conversion optimization",
    "content management", "wordpress", "drupal", "contentful",
    "magento", "shopify", "woocommerce",
    # Communication & Collaboration
    "slack", "microsoft teams", "zoom", "webex", "cisco webex",
    "google meet",
    # Integration & Automation
    "zapier", "make", "power automate",
    "twilio", "sendgrid", "stripe", "plaid",
    "airtable",
    # Certifications (as searchable terms)
    "aws certified", "azure certified", "gcp certified",
    "cissp", "cism", "cisa", "ceh", "oscp", "comptia security+",
    "ccna", "ccnp", "ccie",
    "pmp", "prince2", "itil", "togaf", "cobit",
    "cmmi", "safe", "csm", "psm",
    "cpa", "cfa", "frm", "acca", "cia", "cma",
    "scrum master", "product owner", "safe agilist",
    # Methodologies (also searchable)
    "devops", "devsecops", "mlops", "dataops", "aiops",
    "tdd", "bdd", "atdd",
    "oop", "object-oriented programming",
    "functional programming", "reactive programming",
    "microservices", "serverless",
    "event-driven", "domain-driven design", "ddd",
    "sdlc", "software development life cycle",
    # Additional O*NET widely-used tools
    "adobe dreamweaver", "adobe premiere pro", "adobe captivate",
    "adobe coldfusion", "adobe framemaker",
    "autodesk inventor", "autodesk 3ds max", "autodesk maya",
    "autodesk land desktop",
    "dassault systemes catia",
    "ibm cognos", "ibm informix", "ibm maximo",
    "ibm rational", "ibm websphere",
    "oracle jd edwards", "oracle hyperion",
    "oracle primavera", "oracle taleo", "oracle weblogic",
    "sap businessobjects", "sap crystal reports",
    "sap powerbuilder",
    "filemaker pro", "lotus notes",
    "lexisnexis", "westlaw",
    "mathworks simulink", "mathcad",
    "corel wordperfect",
    "linkedin", "instagram", "youtube", "twitter",
    "dropbox", "box", "evernote",
    "logmein gotomeeting",
    "vmware", "norton", "mcafee", "solarwinds",
}


def _build_tier1() -> set[str]:
    """Build the combined Tier 1 known-skills set."""
    combined = set()
    combined.update(s.lower() for s in ONET_SKILLS)
    combined.update(s.lower() for s in ONET_KNOWLEDGE)
    combined.update(s.lower() for s in ONET_HOT_TECHNOLOGIES)
    combined.update(s.lower() for s in ONET_SOFTWARE_CATEGORIES)
    combined.update(s.lower() for s in TECH_SKILLS)

    # Import SG skills if available
    try:
        from sg_skills import ALL_SG_TERMS
        combined.update(s.lower() for s in ALL_SG_TERMS)
    except ImportError:
        log.warning("sg_skills module not found, skipping SG terms")

    return combined


TIER1_SKILLS: set[str] = _build_tier1()



_tier2_cache: set[str] | None = None


def load_tier2_skills() -> set[str]:
    """Load Tier 2 skills from the learned skills JSON file."""
    global _tier2_cache
    if _tier2_cache is not None:
        return _tier2_cache

    try:
        from build_learned_skills import load_learned_skills
        _tier2_cache = load_learned_skills()
    except (ImportError, Exception):
        _tier2_cache = set()

    return _tier2_cache



def classify_skill_tier(term: str, jd_frequency: int = 0) -> int:
    """Classify a skill term into tiers 1, 2, or 3.

    Args:
        term: The skill term to classify (case-insensitive).
        jd_frequency: How many JDs this term appears in (for Tier 2).

    Returns:
        1 = Known skill (O*NET / SG SFw / curated tech)
        2 = JD-learned skill (appears in 50+ JDs)
        3 = Low confidence
    """
    lowered = term.lower().strip()
    if not lowered:
        return 3

    # Check Tier 1
    if lowered in TIER1_SKILLS:
        return 1

    # Check Tier 2 (from learned skills file or frequency)
    if jd_frequency >= 50:
        return 2
    tier2 = load_tier2_skills()
    if lowered in tier2:
        return 2

    return 3
