import React, { useState } from 'react';
import { ChevronDown, ChevronRight, Settings2, Info } from 'lucide-react';

// ─── OpenAI Chat Completions parameter definitions ────────────────────────────

type ParamType =
  | 'number'      // integer or float slider / number input
  | 'float'       // float with step
  | 'boolean'     // toggle
  | 'string'      // free text
  | 'enum'        // select from fixed list
  | 'json'        // JSON textarea (for objects/arrays)
  | 'integer';

interface ParamOption {
  value: string;
  label: string;
}

interface ParamDef {
  key: string;
  label: string;
  description: string;
  type: ParamType;
  min?: number;
  max?: number;
  step?: number;
  options?: ParamOption[];
  placeholder?: string;
  defaultValue?: any;
}

const OPENAI_PARAMS: ParamDef[] = [
  {
    key: 'frequency_penalty',
    label: 'Frequency Penalty',
    description:
      'Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, decreasing the likelihood of repeating the same line verbatim.',
    type: 'float',
    min: -2,
    max: 2,
    step: 0.1,
    defaultValue: 0,
  },
  {
    key: 'presence_penalty',
    label: 'Presence Penalty',
    description:
      'Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, increasing the model\'s likelihood to talk about new topics.',
    type: 'float',
    min: -2,
    max: 2,
    step: 0.1,
    defaultValue: 0,
  },
  {
    key: 'top_p',
    label: 'Top P (Nucleus Sampling)',
    description:
      'An alternative to sampling with temperature. The model considers only the tokens comprising the top_p probability mass. 0.1 means only the tokens comprising the top 10% probability mass are considered. It is generally recommended to alter this or temperature, but not both.',
    type: 'float',
    min: 0,
    max: 1,
    step: 0.05,
    defaultValue: 1,
  },
  {
    key: 'n',
    label: 'Number of Completions (n)',
    description:
      'How many chat completion choices to generate for each input message. Note that you will be charged based on the number of generated tokens across all choices.',
    type: 'integer',
    min: 1,
    max: 128,
    step: 1,
    defaultValue: 1,
  },
  {
    key: 'seed',
    label: 'Seed',
    description:
      'If specified, the system will make a best effort to sample deterministically, such that repeated requests with the same seed and parameters should return the same result. Determinism is not guaranteed.',
    type: 'integer',
    min: 0,
    max: 2147483647,
    step: 1,
    placeholder: 'e.g. 42',
  },
  {
    key: 'stop',
    label: 'Stop Sequences',
    description:
      'Up to 4 sequences where the API will stop generating further tokens. Enter as a JSON array of strings, e.g. ["\\n", "END"].',
    type: 'json',
    placeholder: '["\\n", "END"]',
  },
  {
    key: 'logit_bias',
    label: 'Logit Bias',
    description:
      'Modify the likelihood of specified tokens appearing in the completion. Maps token IDs (strings) to an associated bias value from -100 to 100. Enter as a JSON object, e.g. {"50256": -100}.',
    type: 'json',
    placeholder: '{"50256": -100}',
  },
  {
    key: 'logprobs',
    label: 'Log Probabilities',
    description:
      'Whether to return log probabilities of the output tokens or not. If true, returns the log probabilities of each output token returned in the content of message.',
    type: 'boolean',
    defaultValue: false,
  },
  {
    key: 'top_logprobs',
    label: 'Top Logprobs',
    description:
      'An integer between 0 and 20 specifying the number of most likely tokens to return at each token position, each with an associated log probability. logprobs must be set to true to use this.',
    type: 'integer',
    min: 0,
    max: 20,
    step: 1,
    defaultValue: 0,
  },
  {
    key: 'response_format',
    label: 'Response Format',
    description:
      'An object specifying the format that the model must output. When Structured JSON Outputs is enabled above, this setting is managed automatically using the application\'s JSON schema. Disable Structured JSON Outputs above to configure custom response formats (e.g. {"type": "json_object"}).',
    type: 'json',
    placeholder: '{"type": "json_object"}',
  },
  {
    key: 'service_tier',
    label: 'Service Tier',
    description:
      'Specifies the latency tier to use for processing the request. "auto" uses scale tier credits when available. "default" uses the standard tier. "flex" enables the Flex Processing tier.',
    type: 'enum',
    options: [
      { value: 'auto', label: 'auto' },
      { value: 'default', label: 'default' },
      { value: 'flex', label: 'flex' },
    ],
    defaultValue: 'auto',
  },
  {
    key: 'stream',
    label: 'Stream',
    description:
      'If set, partial message deltas will be sent as server-sent events. Note: This app does not support streaming UI; enabling this may break processing.',
    type: 'boolean',
    defaultValue: false,
  },
  {
    key: 'parallel_tool_calls',
    label: 'Parallel Tool Calls',
    description:
      'Whether to enable parallel function calling during tool use. Defaults to true. Disable if you need deterministic sequential tool calls.',
    type: 'boolean',
    defaultValue: true,
  },
  {
    key: 'reasoning_effort',
    label: 'Reasoning Effort',
    description:
      'Constrains the effort on reasoning for reasoning models (e.g. o1, o3, Qwen). Official supported examples: low, medium, high. Any custom value (e.g. "none") is also supported.',
    type: 'string',
    placeholder: 'e.g. low, medium, high, none',
    defaultValue: '',
  },
  {
    key: 'store',
    label: 'Store Completions',
    description:
      'Whether or not to store the output of this chat completion request for use in model distillation or evals.',
    type: 'boolean',
    defaultValue: false,
  },
  {
    key: 'user',
    label: 'User Identifier',
    description:
      'A unique identifier representing your end-user, which can help OpenAI monitor and detect abuse.',
    type: 'string',
    placeholder: 'user-1234',
  },
  {
    key: 'metadata',
    label: 'Metadata',
    description:
      'Developer-defined tags and values used for filtering completions in the dashboard. Enter as a JSON object, e.g. {"env":"production"}.',
    type: 'json',
    placeholder: '{"env": "production"}',
  },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function tryParseJson(val: string): any {
  try {
    return JSON.parse(val);
  } catch {
    return val; // return raw string if invalid — validation will catch it
  }
}

function jsonValid(val: string): boolean {
  try {
    JSON.parse(val);
    return true;
  } catch {
    return false;
  }
}

function valueToString(val: any): string {
  if (val === null || val === undefined) return '';
  if (typeof val === 'object') return JSON.stringify(val, null, 2);
  return String(val);
}

// ─── Per-row component ────────────────────────────────────────────────────────

interface ParamRowProps {
  def: ParamDef;
  enabled: boolean;
  value: any;
  useStructuredOutputs?: boolean;
  onToggle: (key: string, enabled: boolean) => void;
  onChange: (key: string, value: any) => void;
}

const ParamRow: React.FC<ParamRowProps> = ({ def, enabled, value, useStructuredOutputs, onToggle, onChange }) => {
  const [showTooltip, setShowTooltip] = useState(false);
  const [jsonError, setJsonError] = useState(false);

  const isOverridden = def.key === 'response_format' && (useStructuredOutputs ?? true);
  const currentValue = value !== undefined ? value : def.defaultValue;

  const handleJsonChange = (raw: string) => {
    const ok = !raw || jsonValid(raw);
    setJsonError(!ok);
    onChange(def.key, raw ? tryParseJson(raw) : undefined);
  };

  const renderInput = () => {
    if (!enabled) return null;

    switch (def.type) {
      case 'boolean':
        return (
          <button
            type="button"
            role="switch"
            disabled={isOverridden}
            aria-checked={!!currentValue}
            onClick={() => !isOverridden && onChange(def.key, !currentValue)}
            className={`
              relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2
              ${currentValue ? 'bg-primary' : 'bg-input'}
              ${isOverridden ? 'opacity-50 cursor-not-allowed' : ''}
            `}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow-sm transition-transform ${
                currentValue ? 'translate-x-4.5' : 'translate-x-0.5'
              }`}
            />
          </button>
        );

      case 'enum':
        return (
          <select
            disabled={isOverridden}
            value={currentValue ?? def.defaultValue ?? ''}
            onChange={(e) => onChange(def.key, e.target.value)}
            className="h-8 rounded-md border border-input bg-transparent px-2 py-1 text-xs text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring min-w-[120px] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {def.options?.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        );

      case 'float':
        return (
          <div className="flex items-center gap-2">
            <input
              type="range"
              disabled={isOverridden}
              min={def.min ?? 0}
              max={def.max ?? 1}
              step={def.step ?? 0.1}
              value={currentValue ?? def.defaultValue ?? 0}
              onChange={(e) => onChange(def.key, parseFloat(e.target.value))}
              className="w-24 accent-primary disabled:cursor-not-allowed disabled:opacity-50"
            />
            <input
              type="number"
              disabled={isOverridden}
              min={def.min}
              max={def.max}
              step={def.step}
              value={currentValue ?? def.defaultValue ?? 0}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                if (!isNaN(v)) onChange(def.key, v);
              }}
              className="w-16 h-8 rounded-md border border-input bg-transparent px-2 text-xs text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>
        );

      case 'integer':
        return (
          <input
            type="number"
            disabled={isOverridden}
            min={def.min}
            max={def.max}
            step={def.step ?? 1}
            value={currentValue ?? def.defaultValue ?? ''}
            placeholder={def.placeholder}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              onChange(def.key, isNaN(v) ? undefined : v);
            }}
            className="h-8 w-28 rounded-md border border-input bg-transparent px-2 text-xs text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
          />
        );

      case 'number':
        return (
          <input
            type="number"
            disabled={isOverridden}
            min={def.min}
            max={def.max}
            step={def.step}
            value={currentValue ?? def.defaultValue ?? ''}
            placeholder={def.placeholder}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              onChange(def.key, isNaN(v) ? undefined : v);
            }}
            className="h-8 w-28 rounded-md border border-input bg-transparent px-2 text-xs text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
          />
        );

      case 'string':
        return (
          <div className="flex flex-col gap-1">
            <input
              type="text"
              disabled={isOverridden}
              value={currentValue ?? ''}
              placeholder={def.placeholder}
              onChange={(e) => onChange(def.key, e.target.value || undefined)}
              className="h-8 w-44 rounded-md border border-input bg-transparent px-2 text-xs text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 font-mono"
            />
            {def.key === 'reasoning_effort' && (
              <span className="text-[10px] text-muted-foreground">
                Official examples: <code className="text-primary">low</code>, <code className="text-primary">medium</code>, <code className="text-primary">high</code>
              </span>
            )}
          </div>
        );

      case 'json':
        return (
          <div className="flex flex-col gap-1 w-full max-w-sm">
            <textarea
              rows={2}
              disabled={isOverridden}
              value={valueToString(currentValue)}
              placeholder={def.placeholder}
              onChange={(e) => handleJsonChange(e.target.value)}
              className={`w-full rounded-md border px-2 py-1 text-xs font-mono text-foreground shadow-sm focus:outline-none focus:ring-1 bg-transparent resize-none disabled:cursor-not-allowed disabled:opacity-50
                ${jsonError ? 'border-destructive focus:ring-destructive' : 'border-input focus:ring-ring'}
              `}
            />
            {jsonError && (
              <span className="text-xs text-destructive">Invalid JSON</span>
            )}
          </div>
        );

      default:
        return null;
    }
  };

  const isJsonType = def.type === 'json';

  return (
    <div
      className={`
        flex gap-3 rounded-lg border px-3 py-2.5 transition-colors
        ${isOverridden
          ? 'opacity-60 bg-muted/10 border-border'
          : enabled
          ? 'border-primary/30 bg-primary/5'
          : 'border-border bg-transparent opacity-60'}
        ${isJsonType ? 'flex-col' : 'flex-row items-center'}
      `}
    >
      {/* Left: checkbox + label + badge + tooltip */}
      <div className={`flex items-center gap-2 ${isJsonType ? 'w-full' : 'flex-1 min-w-0'}`}>
        {/* Checkbox toggle */}
        <input
          type="checkbox"
          id={`adv-param-${def.key}`}
          checked={enabled}
          disabled={isOverridden}
          onChange={(e) => !isOverridden && onToggle(def.key, e.target.checked)}
          className="h-3.5 w-3.5 accent-primary shrink-0 cursor-pointer disabled:cursor-not-allowed"
        />
        <label
          htmlFor={`adv-param-${def.key}`}
          className={`text-xs font-medium text-foreground select-none truncate ${
            isOverridden ? 'cursor-not-allowed' : 'cursor-pointer'
          }`}
        >
          {def.label}
        </label>

        {isOverridden && (
          <span className="inline-flex items-center gap-1 rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400 border border-amber-500/20 shrink-0">
            Overridden by Structured JSON Outputs
          </span>
        )}

        {/* Info tooltip */}
        <div className="relative shrink-0">
          <button
            type="button"
            onMouseEnter={() => setShowTooltip(true)}
            onMouseLeave={() => setShowTooltip(false)}
            onFocus={() => setShowTooltip(true)}
            onBlur={() => setShowTooltip(false)}
            className="text-muted-foreground hover:text-foreground transition-colors"
            aria-label={`Info about ${def.label}`}
          >
            <Info className="w-3 h-3" />
          </button>
          {showTooltip && (
            <div className="absolute left-0 top-5 z-50 w-72 rounded-lg border border-border bg-popover text-popover-foreground shadow-lg p-3 text-xs leading-relaxed">
              {def.description}
              {(def.min !== undefined || def.max !== undefined) && (
                <div className="mt-1.5 text-muted-foreground font-mono">
                  Range: {def.min ?? '−∞'} → {def.max ?? '+∞'}
                  {def.step !== undefined ? `, step ${def.step}` : ''}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Right: input */}
      {isJsonType ? (
        <div className="pl-5">{renderInput()}</div>
      ) : (
        <div className="shrink-0">{renderInput()}</div>
      )}
    </div>
  );
};

// ─── Main export ──────────────────────────────────────────────────────────────

interface AdvancedApiParamsProps {
  /** Current extra params stored in model.params (excluding system_prompt / user_prompt) */
  params: Record<string, any>;
  /** Which param keys are currently enabled */
  enabledKeys: Record<string, boolean>;
  useStructuredOutputs?: boolean;
  onChange: (params: Record<string, any>, enabledKeys: Record<string, boolean>) => void;
}

export const AdvancedApiParams: React.FC<AdvancedApiParamsProps> = ({
  params,
  enabledKeys,
  useStructuredOutputs,
  onChange,
}) => {
  const [open, setOpen] = useState(false);

  const handleToggle = (key: string, enabled: boolean) => {
    const nextEnabled = { ...enabledKeys, [key]: enabled };
    onChange(params, nextEnabled);
  };

  const handleChange = (key: string, value: any) => {
    const nextParams = { ...params };
    if (value === undefined || value === '') {
      delete nextParams[key];
    } else {
      nextParams[key] = value;
    }
    onChange(nextParams, enabledKeys);
  };

  const enabledCount = OPENAI_PARAMS.filter((p) => enabledKeys[p.key]).length;

  return (
    <div className="rounded-xl border border-border overflow-hidden">
      {/* Header / toggle */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-5 py-3.5 bg-accent/30 hover:bg-accent/50 transition-colors text-left"
      >
        <div className="flex items-center gap-2.5">
          <Settings2 className="w-4 h-4 text-primary shrink-0" />
          <span className="text-sm font-semibold text-foreground">Advanced API Parameters</span>
          {enabledCount > 0 && (
            <span className="inline-flex items-center justify-center rounded-full bg-primary text-primary-foreground text-[10px] font-bold w-4.5 h-4.5 px-1.5 py-0.5 leading-none">
              {enabledCount}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span>{open ? 'Collapse' : 'Expand'}</span>
          {open ? (
            <ChevronDown className="w-4 h-4 transition-transform" />
          ) : (
            <ChevronRight className="w-4 h-4 transition-transform" />
          )}
        </div>
      </button>

      {/* Collapsible body */}
      {open && (
        <div className="px-5 py-4 space-y-2 bg-card">
          <p className="text-xs text-muted-foreground mb-3">
            Check a parameter to activate it. Only enabled parameters are sent to the API. Hover{' '}
            <Info className="inline w-3 h-3 mb-0.5" /> for full OpenAI documentation.
          </p>

          {OPENAI_PARAMS.map((def) => (
            <ParamRow
              key={def.key}
              def={def}
              enabled={!!enabledKeys[def.key]}
              value={params[def.key]}
              useStructuredOutputs={useStructuredOutputs}
              onToggle={handleToggle}
              onChange={handleChange}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default AdvancedApiParams;

// ─── Helper exported for ConfigTab to filter enabled params ───────────────────

/** Returns only the params whose key is enabled, for storage / API submission */
export function buildEnabledParams(
  params: Record<string, any>,
  enabledKeys: Record<string, boolean>,
): Record<string, any> {
  return Object.fromEntries(
    Object.entries(params).filter(([k]) => enabledKeys[k]),
  );
}
