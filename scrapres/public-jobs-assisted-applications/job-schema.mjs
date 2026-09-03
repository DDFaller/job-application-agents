export const jobSchema = {
  type: "object",
  properties: {
    source_portal: {
      type: "string",
      enum: ["choisir-service-public", "emploi-territorial", "france-travail"]
    },
    source_url: { type: "string" },
    reference: { type: "string" },
    title: { type: "string" },
    employer: { type: "string" },
    location: { type: "string" },
    department: { type: "string" },
    region: { type: "string" },
    category: { type: "string" },
    job_family: { type: "string" },
    employment_type: { type: "string" },
    open_to_contractors: { type: "string" },
    grades: { type: "array", items: { type: "string" } },
    work_time: { type: "string" },
    management: { type: "string" },
    experience_level: { type: "string" },
    remote_work: { type: "string" },
    start_date: { type: "string" },
    publication_date: { type: "string" },
    application_deadline: { type: "string" },
    salary: { type: "string" },
    summary: { type: "string" },
    responsibilities: { type: "array", items: { type: "string" } },
    requirements: { type: "array", items: { type: "string" } },
    preferred_qualifications: { type: "array", items: { type: "string" } },
    skills: { type: "array", items: { type: "string" } },
    languages: { type: "array", items: { type: "string" } },
    application_process: { type: "string" },
    evidence: {
      type: "array",
      items: {
        type: "object",
        properties: {
          field: { type: "string" },
          excerpt: { type: "string" }
        },
        required: ["field", "excerpt"]
      }
    }
  },
  required: [
    "source_portal",
    "source_url",
    "reference",
    "title",
    "employer",
    "location",
    "department",
    "region",
    "category",
    "job_family",
    "employment_type",
    "open_to_contractors",
    "grades",
    "work_time",
    "management",
    "experience_level",
    "remote_work",
    "start_date",
    "publication_date",
    "application_deadline",
    "salary",
    "summary",
    "responsibilities",
    "requirements",
    "preferred_qualifications",
    "skills",
    "languages",
    "application_process",
    "evidence"
  ]
};

export function assertJobShape(job) {
  for (const key of jobSchema.required) {
    if (!(key in job)) throw new Error(`Campo ausente na resposta Gemini: ${key}`);
  }

  const arrayFields = [
    "grades",
    "responsibilities",
    "requirements",
    "preferred_qualifications",
    "skills",
    "languages",
    "evidence"
  ];
  for (const field of arrayFields) {
    if (!Array.isArray(job[field])) {
      throw new Error(`Campo inválido na resposta Gemini: ${field}`);
    }
  }
}
