## What and why
<!-- One paragraph. Link the issue: Closes #123 -->

## Change for runners
<!-- Plain language for the clinical reviewer and the release notes: what a runner or a physio
     will see or be told differently. "None" for internal changes. -->

## Gates
- [ ] Tests added or updated; backend tests, type check and i18n merge pass
- [ ] `engine` / `safety` label if this changes what runners are told about their health (needs the clinical sign-off in Team Console → Approvals)
- [ ] `security` label and a `/cso` report if this touches login, consent, physio access, exports or AI calls with user data
- [ ] `/review` run; `/qa` on staging for UI changes
- [ ] No production health data, secrets or model names in the diff, the description or screenshots

## Screenshots
<!-- Demo runners only -->
