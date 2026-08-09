# Design Document: Response Format UI Override Handling

**Date**: 2026-08-09  
**Status**: Approved  

## Context & Problem Statement
The application provides two settings related to OpenAI JSON responses:
1. **Structured JSON Outputs** (`use_structured_outputs`): A top-level toggle that enforces native JSON Schema formatting for AI responses.
2. **Response Format** (`response_format`): An advanced API parameter in *Advanced API Parameters* allowing raw JSON parameters (such as `{"type": "json_object"}`).

In the backend (`ai_client.py`), `use_structured_outputs=True` explicitly takes precedence and overwrites any `response_format` parameter passed in `extra_params`. However, the UI previously showed `response_format` as active and editable even when `use_structured_outputs` was enabled, causing potential confusion for users.

## Proposed Solution
We implement visual feedback and interaction locking in `AdvancedApiParams.tsx` when `use_structured_outputs` is enabled.

### 1. Property Flow
- In `webui/src/components/config/ConfigTab.tsx`, pass `useStructuredOutputs={formData.model?.use_structured_outputs ?? true}` to `<AdvancedApiParams />`.
- In `webui/src/components/config/AdvancedApiParams.tsx`, add `useStructuredOutputs?: boolean` to `AdvancedApiParamsProps`.

### 2. UI Behavior for `response_format`
When `def.key === 'response_format'` and `useStructuredOutputs` is `true`:
- **Visual Styling**: Row opacity reduced (`opacity-60`), background tinted to reflect inactive state.
- **Controls**: Checkbox and JSON input controls are disabled (`disabled={true}`).
- **Badge**: Render an inline amber badge next to the label: `Overridden by Structured JSON Outputs`.
- **Tooltip**: Hover tooltip clarifies that disabling "Structured JSON Outputs" above unlocks custom `response_format` options.

### 3. Unlock Behavior
When the user toggles "Structured JSON Outputs" to `OFF`:
- The override badge is removed.
- `response_format` row returns to full opacity.
- Controls are unlocked and interactive.

## Verification Criteria
- When `use_structured_outputs` is `true` (default), `response_format` is locked with the override badge visible.
- When `use_structured_outputs` is `false`, `response_format` can be checked and edited.
- TypeScript build (`npm run build` or Vite build) passes cleanly without type errors.
