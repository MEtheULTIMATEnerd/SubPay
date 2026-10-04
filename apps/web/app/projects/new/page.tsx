"use client";
import { useRouter } from "next/navigation";
import { createProject } from "@/lib/api";
import { ProjectForm } from "@/components/projects";
import { Page, PageHeader } from "@/components/ui";

export default function NewProjectPage() {
  const router = useRouter();
  return (
    <Page>
      <div className="mx-auto max-w-2xl">
        <PageHeader title="New project" sub="Next you'll upload the subcontract so SubPay can build your claim schedule." />
        <div className="card p-6 sm:p-8">
          <ProjectForm
            submitLabel="Create project"
            onCancel={() => router.back()}
            onSubmit={(f) => router.push(`/projects/${createProject(f)}/contracts`)}
          />
        </div>
      </div>
    </Page>
  );
}
