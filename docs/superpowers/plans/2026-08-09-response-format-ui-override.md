# Response Format UI Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Indicate in the UI when `response_format` in Advanced API Parameters is overridden by the top-level "Structured JSON Outputs" toggle, locking its input controls and adding clear visual feedback.

**Architecture:** Pass `useStructuredOutputs` state down from `ConfigTab.tsx` to `AdvancedApiParams.tsx`. When `def.key === 'response_format'` and `useStructuredOutputs` is `true`, `ParamRow` locks controls, updates opacity, displays an amber override badge, and provides explanatory tooltip guidance.

**Tech Stack:** React, TypeScript, Tailwind CSS, Lucide icons.

## Global Constraints

- Preserve existing model configuration data structures and API contract.
- Use existing UI theme tokens and styling patterns (Tailwind classes).

---

### Task 1: Update `AdvancedApiParams.tsx` and `ConfigTab.tsx`

**Files:**
- Modify: `webui/src/components/config/AdvancedApiParams.tsx`
- Modify: `webui/src/components/config/ConfigTab.tsx:568-575`

**Interfaces:**
- Consumes: `formData.model.use_structured_outputs` from `ConfigTab.tsx`
- Produces: `useStructuredOutputs` prop in `AdvancedApiParamsProps`

- [ ] **Step 1: Update `AdvancedApiParamsProps` interface and `ParamRow` component in `AdvancedApiParams.tsx`**

Edit `webui/src/components/config/AdvancedApiParams.tsx`:
1. Add `useStructuredOutputs?: boolean` to `AdvancedApiParamsProps`.
2. Pass `useStructuredOutputs` down to `ParamRow`.
3. In `ParamRow`, compute `const isOverridden = def.key === 'response_format' && (useStructuredOutputs ?? true);`.
4. When `isOverridden`:
   - Disable checkbox: `disabled={isOverridden}`.
   - Disable inputs (textarea, select, number/text inputs) by passing `disabled={isOverridden}`.
   - If `isOverridden`, display inline badge next to label:
     ```tsx
     {isOverridden && (
       <span className="inline-flex items-center gap-1 rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400 border border-amber-500/20 shrink-0">
         Overridden by Structured JSON Outputs
       </span>
     )}
     ```
   - Update container styling to apply `opacity-60 bg-muted/10` when `isOverridden`.
5. Update `response_format` description in `OPENAI_PARAMS`:
   `'An object specifying the format that the model must output. When Structured JSON Outputs is enabled above, this setting is managed automatically using the application\'s JSON schema. Disable Structured JSON Outputs above to configure custom response formats (e.g. {"type": "json_object"}).'`

- [ ] **Step 2: Update `ConfigTab.tsx` to pass `useStructuredOutputs`**

In `webui/src/components/config/ConfigTab.tsx`:
Pass `useStructuredOutputs={formData.model?.use_structured_outputs ?? true}` to `<AdvancedApiParams />`.

- [ ] **Step 3: Build WebUI and verify TypeScript compilation**

Run: `cd webui && npm run build`
Expected: Build succeeds with 0 errors.

- [ ] **Step 4: Commit changes**

```bash
git add webui/src/components/config/AdvancedApiParams.tsx webui/src/components/config/ConfigTab.tsx
git commit -m "feat(webui): lock response_format in advanced params when structured outputs is enabled"
```
