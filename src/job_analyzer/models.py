"""Data models: the shape we want Claude's answers to have.

With structured outputs, these Pydantic models are converted to a JSON Schema and
sent to the API. The API then *guarantees* Claude's reply matches it, so we
never have to parse free-form text ourselves.

The `description=` texts are sent to Claude too: they are part of the prompt.

Values that our code compares later (country, language level, salary numbers)
are *normalized* during extraction, so plain Python can compare them reliably.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Seniority = Literal["intern", "junior", "mid", "senior", "lead", "unknown"]
RemotePolicy = Literal["remote", "hybrid", "onsite", "unknown"]
WorkArrangement = Literal["remote", "hybrid", "onsite"]

# CEFR levels, lowest to highest, plus "native" and "unknown".
LanguageLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2", "native", "unknown"]
LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2", "native"]


class Place(BaseModel):
    city: str | None = Field(description="City name in English, or null if not stated.")
    country: str | None = Field(
        description="Country name in English (e.g. 'Romania', 'Germany'), or null if unknown."
    )

    def __str__(self) -> str:
        return ", ".join(p for p in (self.city, self.country) if p) or "unknown"


class LanguageRequirement(BaseModel):
    language: str = Field(description="Language name in English, e.g. 'English', 'German'.")
    level: LanguageLevel = Field(
        description=(
            "CEFR level. Map words to levels: basic/elementary=A2, intermediate/good=B1, "
            "upper-intermediate/very good=B2, fluent/advanced=C1, proficient=C2, "
            "native/mother tongue=native. Use 'unknown' if no level is given."
        )
    )

    def __str__(self) -> str:
        return self.language if self.level == "unknown" else f"{self.language} {self.level}"


class LanguageGroup(BaseModel):
    """One language requirement that ANY of several languages can satisfy."""

    any_of: list[LanguageRequirement] = Field(
        description=(
            "The candidate needs at least ONE of these. One item for a plain requirement "
            "('English required'); several for alternatives ('French or Dutch')."
        )
    )

    def __str__(self) -> str:
        return " or ".join(str(l) for l in self.any_of)


class SalaryInfo(BaseModel):
    minimum: float | None = Field(description="Lower bound as a plain number, e.g. 4500.")
    maximum: float | None = Field(description="Upper bound as a plain number, or null.")
    currency: str = Field(description="ISO currency code, e.g. 'EUR', 'RON', 'USD'.")
    basis: Literal["gross", "net", "unknown"]
    period: Literal["hour", "month", "year", "unknown"]
    raw_text: str = Field(description="The salary exactly as written in the posting.")


class JobRequirements(BaseModel):
    """Structured information extracted from one job posting."""

    title: str = Field(description="Job title as written in the posting.")
    company: str | None = Field(description="Company name, or null if not stated.")
    seniority: Seniority = Field(
        description="Seniority level. Use 'unknown' if the posting doesn't make it clear."
    )
    location: Place | None = Field(description="Where the job is based, or null if not stated.")
    remote_policy: RemotePolicy
    years_experience_min: int | None = Field(
        description="Minimum years of experience required, or null if not stated."
    )
    must_have_skills: list[str] = Field(
        description="Skills/technologies the posting says are required."
    )
    nice_to_have_skills: list[str] = Field(
        description="Skills marked as optional, a plus, bonus, or preferred."
    )
    languages_required: list[LanguageGroup] = Field(
        description=(
            "REQUIRED spoken languages as groups; the candidate must satisfy every group. "
            "'English and French' = two groups. 'French or Dutch' = one group with both. "
            "'English + French or Dutch' = two groups. Empty list if none are required."
        )
    )
    languages_nice_to_have: list[LanguageRequirement] = Field(
        description="Languages marked as a plus, an advantage or preferred, but not required."
    )
    responsibilities: list[str] = Field(description="Main duties, each as a short phrase.")
    salary: SalaryInfo | None = Field(description="Salary, or null if the posting doesn't state one.")
    posted_date: str | None = Field(
        default=None,
        description=(
            "Date the job was posted as YYYY-MM-DD if the posting shows it ('posted 3 days ago' -> "
            "compute from today's date). Null if not shown."
        ),
    )
    red_flags: list[str] = Field(
        description=(
            "Warning signs for a candidate, e.g. unpaid overtime, unrealistic "
            "requirements, vague pay. Empty list if none."
        )
    )
    summary: str = Field(description="Two-sentence plain-English summary of the role.")


VERBATIM = " Copy it exactly as written in the CV: do not rewrite, shorten, translate or correct it."


class WorkExperience(BaseModel):
    job_title: str = Field(description="Job title." + VERBATIM)
    company: str = Field(description="Employer name." + VERBATIM)
    location: str | None = Field(description="Location as written, or null if not stated.")
    start_date: str | None = Field(description="Start date as written (e.g. 'Mar 2021'), or null.")
    end_date: str | None = Field(
        description="End date as written. Use 'Present' if the CV says it is the current job. Null if not stated."
    )
    description: str = Field(
        description=(
            "All responsibilities and achievements for this job." + VERBATIM
            + " Put each bullet point on its own line, starting with '- '. Empty string if none."
        )
    )


class Education(BaseModel):
    institution: str = Field(description="School or university name." + VERBATIM)
    degree: str | None = Field(description="Degree or qualification as written, or null.")
    field_of_study: str | None = Field(description="Field/major as written, or null.")
    location: str | None = Field(description="Location as written, or null.")
    start_date: str | None = Field(description="Start date as written, or null.")
    end_date: str | None = Field(description="End/graduation date as written, or null.")
    details: str | None = Field(
        description="Grade, thesis, honours or other details." + VERBATIM + " Null if none."
    )


class Certification(BaseModel):
    name: str = Field(description="Certification name." + VERBATIM)
    issuer: str | None = Field(description="Issuing organization, or null.")
    issue_date: str | None = Field(description="Date obtained as written, or null.")
    expiry_date: str | None = Field(description="Expiry date as written, or null.")
    credential_id: str | None = Field(description="Credential ID, or null.")
    url: str | None = Field(description="Verification URL, or null.")
    details: str | None = Field(
        default=None, description="Any extra line written under this certification." + VERBATIM + " Null if none."
    )


class ContactInfo(BaseModel):
    full_name: str | None = Field(description="Candidate's full name." + VERBATIM + " Null if not stated.")
    email: str | None = Field(description="Email address as written, or null.")
    phone: str | None = Field(description="Phone number as written, including country code, or null.")
    address: str | None = Field(description="Postal address as written (street, number, postcode, city), or null.")
    linkedin: str | None = Field(description="LinkedIn profile URL if the CV shows it, else null. Never guess a URL.")
    website: str | None = Field(description="Personal website or portfolio URL, or null.")


class CVDetails(BaseModel):
    """Full CV sections, copied verbatim, for filling in application forms."""

    contact: ContactInfo | None = Field(
        default=None, description="The candidate's contact details from the CV header or contact section."
    )
    experience: list[WorkExperience] = Field(description="Every job, in the same order as the CV.")
    education: list[Education] = Field(description="Every education entry, in CV order.")
    certifications: list[Certification] = Field(
        description="Every certification/license/course certificate, in CV order. Empty if none."
    )


class FitAssessment(BaseModel):
    """Claude's judgement of how well the candidate fits one posting (the part code can't do)."""

    fit_score: int = Field(
        description=(
            "0-100. How well the CV's actual experience covers the posting's must-have skills and "
            "responsibilities. 80-100: strong, apply now. 60-79: good, some gaps. 40-59: stretch. "
            "Below 40: poor fit. Judge equivalents (e.g. EKS counts as Kubernetes)."
        )
    )
    matching_skills: list[str] = Field(
        description="Must-have skills the CV clearly shows, each with evidence, e.g. 'Terraform (Acme Corp, IaC automation)'."
    )
    gaps: list[str] = Field(description="Must-have skills or requirements the CV does not show.")
    how_to_address: str = Field(
        description="One or two sentences: the most convincing way to address the biggest gap in an application."
    )
    summary: str = Field(description="One-sentence verdict.")

    @field_validator("fit_score")
    @classmethod
    def _score_range(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("fit_score must be between 0 and 100")
        return v


class PayRange(BaseModel):
    gross_monthly_low: float = Field(description="Low end, monthly gross (contractors: monthly invoiced amount).")
    gross_monthly_high: float = Field(description="High end, monthly gross (contractors: monthly invoiced amount).")
    net_monthly_low: float = Field(description="Monthly take-home for the low end.")
    net_monthly_high: float = Field(description="Monthly take-home for the high end.")

    @model_validator(mode="after")
    def _consistent(self):
        if self.gross_monthly_low > self.gross_monthly_high or self.net_monthly_low > self.net_monthly_high:
            raise ValueError("low must not be above high")
        if self.net_monthly_low > self.gross_monthly_low or self.net_monthly_high > self.gross_monthly_high:
            raise ValueError("net must not be above gross")
        if min(self.gross_monthly_low, self.net_monthly_low) <= 0:
            raise ValueError("amounts must be positive")
        return self


class SalarySource(BaseModel):
    name: str = Field(description="Who published the figure, e.g. 'Paylab Belgium, Cloud Engineer'.")
    url: str = Field(description="The page the figure comes from (a page you actually opened or got as a search result).")
    figure: str = Field(description="What it says, with its period and gross/net, e.g. '€6,800/month gross at 5 years'.")


class SalaryEstimate(BaseModel):
    """Claude's estimate of what a job pays, for postings that state no salary.

    Two measures: what the market pays for the ROLE, and where THIS candidate would likely
    land. Not an offer: sources show where the numbers come from, and confidence says how
    much to trust them.
    """

    contract_type: Literal["employee", "contractor", "unknown"] = Field(
        description="Contract the posting offers: 'employee' (payroll), 'contractor' (freelance/B2B invoicing), or 'unknown'."
    )
    priced_as: Literal["employee", "contractor"] = Field(
        description="The arrangement the numbers assume (the most likely one when contract_type is 'unknown')."
    )
    pay_market: str = Field(
        description=(
            "Whose pay scale applies, e.g. 'Belgian market', 'US company paying international "
            "contractors in USD', 'European remote band of a US start-up'."
        )
    )
    currency: str = Field(description="ISO currency code of all amounts, e.g. 'EUR'.")
    market: PayRange = Field(description="What the market pays for this ROLE at the level the posting asks for.")
    for_you: PayRange = Field(description="Where THIS candidate would likely land, given their experience and fit.")
    months_per_year: float = Field(
        description="Paid months per year: 13.92 for a Belgian employee (13th month + double holiday pay), 12 for a contractor."
    )
    basis: str = Field(
        description=(
            "Every assumption in one or two sentences: country of tax, household, exchange rate, "
            "contractor expenses, what's excluded (bonus, car, meal vouchers, equity)."
        )
    )
    sources: list[SalarySource] = Field(
        description="Salary data the figures are based on. Empty only if nothing could be found."
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description="How reliable this is. 'low' without sources; 'high' only with the company's own pay band."
    )
    reasoning: str = Field(
        description="Two or three sentences: what set the market band and why the candidate lands where they do."
    )

    @model_validator(mode="after")
    def _grounded(self):
        if not self.sources and self.confidence != "low":
            raise ValueError("an estimate without sources must have confidence 'low'")
        if not 12 <= self.months_per_year <= 15:
            raise ValueError("months_per_year must be between 12 and 15")
        return self

    def yearly_gross(self, r: PayRange) -> tuple[float, float]:
        return r.gross_monthly_low * self.months_per_year, r.gross_monthly_high * self.months_per_year


class CVFacts(BaseModel):
    """Facts read from the user's CV, used as defaults during setup."""

    location: Place | None = Field(description="Where the candidate lives, or null if not stated.")
    suggested_titles: list[str] = Field(
        description="3-5 job titles this candidate is a strong fit for, based on their experience."
    )
    key_skills: list[str] = Field(
        description="The candidate's 5-10 strongest, most marketable skills/technologies."
    )
    languages: list[LanguageRequirement] = Field(
        description="Spoken languages the candidate knows, with level. Empty if none listed."
    )
    years_experience: int | None = Field(
        description="Total years of professional experience, or null if unclear."
    )
