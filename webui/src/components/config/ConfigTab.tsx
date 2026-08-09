import React, { useState, useEffect, useRef } from 'react';
import { useConfig } from '@/hooks/useConfig';
import { useToast } from '@/components/layout/ToastContainer';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import {
  Save,
  Download,
  Upload,
  Folder,
  Cpu,
  FileText,
  Sliders,
  Plus,
  Trash2,
  Loader2,
  Eye,
  EyeOff,
  Sparkles,
} from 'lucide-react';
import type { AppConfig, TagConfig } from '@/types';
import { AdvancedApiParams } from './AdvancedApiParams';

// Keys that live in model.params but are NOT OpenAI API params (handled separately)
const RESERVED_PARAM_KEYS = new Set(['system_prompt', 'user_prompt', '_advanced_enabled']);

/** Extract non-reserved params from model.params for the Advanced section */
function extractAdvancedParams(params?: Record<string, any>): Record<string, any> {
  if (!params) return {};
  return Object.fromEntries(
    Object.entries(params).filter(([k]) => !RESERVED_PARAM_KEYS.has(k))
  );
}

/** Extract the _advanced_enabled map (stored alongside params) */
function extractEnabledMap(params?: Record<string, any>): Record<string, boolean> {
  return (params?._advanced_enabled as Record<string, boolean>) ?? {};
}

const defaultConfig: AppConfig = {
  root_directory: '/data/images',
  model: {
    base_url: 'https://api.openai.com/v1',
    model_name: 'gpt-4o',
    max_tokens: 500,
    temperature: 0.1,
    api_key: '',
    use_structured_outputs: true,
    max_image_dimension: 720,
    image_format: 'webp',
    image_quality: 80,
    concurrency: 1,
    params: {
      system_prompt:
        'You are an expert AI vision assistant specializing in image analysis and metadata tagging.',
      user_prompt:
        'Analyze the image and evaluate each target tag. Assign a confidence score from 0.0 to 1.0 for each tag based strictly on visual evidence.',
    },
  },
  tags: {
    nature: { description: 'Natural landscapes, plants, trees, outdoors', threshold: 0.7 },
    portrait: { description: 'People, faces, close-up human photos', threshold: 0.75 },
    architecture: { description: 'Buildings, structures, urban environments', threshold: 0.7 },
  },
  exclude_patterns: ['*.tmp', '.DS_Store', '.*'],
};

export const ConfigTab: React.FC = () => {
  const { config, loading, saving, saveConfig, exportConfig, importConfig } = useConfig();
  const { showToast } = useToast();

  const [formData, setFormData] = useState<AppConfig>(defaultConfig);
  const [showApiKey, setShowApiKey] = useState<boolean>(false);
  const [newTagName, setNewTagName] = useState<string>('');
  const [newTagDesc, setNewTagDesc] = useState<string>('');
  const [newTagThreshold, setNewTagThreshold] = useState<number>(0.7);
  const [excludePatternInput, setExcludePatternInput] = useState<string>('');

  // Advanced OpenAI API params
  const [advancedParams, setAdvancedParams] = useState<Record<string, any>>({});
  const [advancedEnabled, setAdvancedEnabled] = useState<Record<string, boolean>>({});

  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (config) {
      const mergedParams = {
        system_prompt:
          config.model?.params?.system_prompt ||
          defaultConfig.model.params?.system_prompt,
        user_prompt:
          config.model?.params?.user_prompt ||
          defaultConfig.model.params?.user_prompt,
        ...config.model?.params,
      };

      setFormData({
        ...config,
        model: {
          ...config.model,
          params: mergedParams,
        },
      });
      setExcludePatternInput(config.exclude_patterns ? config.exclude_patterns.join(', ') : '');

      // Populate advanced params from stored config
      setAdvancedParams(extractAdvancedParams(config.model?.params));
      setAdvancedEnabled(extractEnabledMap(config.model?.params));
    }
  }, [config]);

  const handleSave = async () => {
    const excludes = excludePatternInput
      .split(',')
      .map((p) => p.trim())
      .filter((p) => p.length > 0);

    // Merge enabled advanced params into model.params alongside prompts
    const enabledAdvancedParams = Object.fromEntries(
      Object.entries(advancedParams).filter(([k]) => advancedEnabled[k])
    );

    const updatedData: AppConfig = {
      ...formData,
      exclude_patterns: excludes,
      model: {
        ...formData.model,
        params: {
          // Keep reserved params (system_prompt, user_prompt)
          ...Object.fromEntries(
            Object.entries(formData.model?.params ?? {}).filter(([k]) =>
              RESERVED_PARAM_KEYS.has(k) && k !== '_advanced_enabled'
            )
          ),
          // Merge in only the enabled advanced params
          ...enabledAdvancedParams,
          // Persist enabled map so we can re-populate the UI on reload
          _advanced_enabled: advancedEnabled,
        },
      },
    };

    const res = await saveConfig(updatedData);
    if (res.success) {
      showToast('Configuration saved successfully', 'success');
    } else {
      showToast(res.error || 'Failed to save configuration', 'error');
    }
  };

  const handleExport = () => {
    exportConfig();
    showToast('Configuration exported as JSON file', 'success');
  };

  const handleImportClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const parsed = JSON.parse(event.target?.result as string) as AppConfig;
        if (!parsed || typeof parsed !== 'object') {
          throw new Error('Invalid JSON structure');
        }
        importConfig(parsed);
        setFormData(parsed);
        if (parsed.exclude_patterns) {
          setExcludePatternInput(parsed.exclude_patterns.join(', '));
        }
        showToast('Configuration imported! Click Save to persist.', 'success');
      } catch (err: any) {
        showToast('Failed to import configuration: ' + err.message, 'error');
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const handleAddTag = () => {
    const name = newTagName.trim().toLowerCase();
    if (!name) {
      showToast('Tag name cannot be empty', 'warning');
      return;
    }
    if (formData.tags[name]) {
      showToast(`Tag "${name}" already exists`, 'warning');
      return;
    }

    setFormData((prev) => ({
      ...prev,
      tags: {
        ...prev.tags,
        [name]: {
          description: newTagDesc.trim() || undefined,
          threshold: newTagThreshold,
        },
      },
    }));

    setNewTagName('');
    setNewTagDesc('');
    setNewTagThreshold(0.7);
    showToast(`Added tag "${name}"`, 'info');
  };

  const handleRemoveTag = (tagName: string) => {
    setFormData((prev) => {
      const nextTags = { ...prev.tags };
      delete nextTags[tagName];
      return { ...prev, tags: nextTags };
    });
    showToast(`Removed tag "${tagName}"`, 'info');
  };

  const handleUpdateTag = (tagName: string, field: keyof TagConfig, val: any) => {
    setFormData((prev) => ({
      ...prev,
      tags: {
        ...prev.tags,
        [tagName]: {
          ...prev.tags[tagName],
          [field]: val,
        },
      },
    }));
  };

  if (loading && !config) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-3 text-muted-foreground">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
        <p className="text-sm font-medium">Loading configuration settings...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-5xl mx-auto pb-12">
      {/* Top Header & Global Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-card border border-border p-5 rounded-xl shadow-sm">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-primary" />
            Configuration Settings
          </h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Manage system root paths, AI vision backend models, prompts, and tag criteria.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept=".json"
            className="hidden"
          />
          <Button variant="outline" size="sm" onClick={handleImportClick} className="gap-1.5">
            <Upload className="w-4 h-4" />
            Import
          </Button>
          <Button variant="outline" size="sm" onClick={handleExport} className="gap-1.5">
            <Download className="w-4 h-4" />
            Export
          </Button>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={saving}
            className="gap-1.5 font-semibold bg-primary text-primary-foreground hover:bg-primary/90"
          >
            {saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            Save Configuration
          </Button>
        </div>
      </div>

      {/* Section 1: Storage & Directories */}
      <Card className="border-border">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Folder className="w-5 h-5 text-primary" />
            <CardTitle>Storage & Directories</CardTitle>
          </div>
          <CardDescription>
            Specify root image directory and file exclusion patterns for scanning.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">Root Directory Path</label>
            <Input
              value={formData.root_directory || ''}
              onChange={(e) =>
                setFormData((prev) => ({ ...prev, root_directory: e.target.value }))
              }
              placeholder="/data/images"
              className="font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              Base path on server disk containing target image subfolders.
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">Exclude Patterns</label>
            <Input
              value={excludePatternInput}
              onChange={(e) => setExcludePatternInput(e.target.value)}
              placeholder="*.tmp, .DS_Store, .git"
              className="font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              Comma-separated glob patterns to ignore during recursive directory scanning.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Section 2: LLM Model Backend */}
      <Card className="border-border">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Cpu className="w-5 h-5 text-primary" />
            <CardTitle>Model & LLM Backend</CardTitle>
          </div>
          <CardDescription>
            Configure your OpenAI-compatible Vision API connection endpoints and model parameters.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Model Base URL</label>
              <Input
                value={formData.model?.base_url || ''}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    model: { ...prev.model, base_url: e.target.value },
                  }))
                }
                placeholder="https://api.openai.com/v1"
                className="font-mono text-sm"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Model Name</label>
              <Input
                value={formData.model?.model_name || ''}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    model: { ...prev.model, model_name: e.target.value },
                  }))
                }
                placeholder="gpt-4o"
                className="font-mono text-sm"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">API Key</label>
            <div className="relative">
              <Input
                type={showApiKey ? 'text' : 'password'}
                value={formData.model?.api_key || ''}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    model: { ...prev.model, api_key: e.target.value },
                  }))
                }
                placeholder="sk-..."
                className="pr-10 font-mono text-sm"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label={showApiKey ? 'Hide API Key' : 'Show API Key'}
              >
                {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Max Tokens</label>
              <Input
                type="number"
                value={formData.model?.max_tokens || 500}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    model: { ...prev.model, max_tokens: parseInt(e.target.value) || 500 },
                  }))
                }
                className="text-sm"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Temperature</label>
              <Input
                type="number"
                step="0.05"
                min="0"
                max="2"
                value={formData.model?.temperature ?? 0.1}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    model: {
                      ...prev.model,
                      temperature: parseFloat(e.target.value) || 0.1,
                    },
                  }))
                }
                className="text-sm"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Max Image Dimension (px)</label>
              <Input
                type="number"
                step="10"
                value={formData.model?.max_image_dimension || 720}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    model: {
                      ...prev.model,
                      max_image_dimension: parseInt(e.target.value) || 720,
                    },
                  }))
                }
                className="text-sm"
              />
            </div>
          </div>

          {/* Image format, quality & concurrency */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Image Format</label>
              <div className="flex rounded-md border border-input overflow-hidden h-9 text-sm">
                {(['webp', 'jpeg'] as const).map((fmt) => (
                  <button
                    key={fmt}
                    type="button"
                    onClick={() =>
                      setFormData((prev) => ({
                        ...prev,
                        model: { ...prev.model, image_format: fmt },
                      }))
                    }
                    className={`flex-1 transition-colors font-medium uppercase text-xs tracking-wide ${
                      (formData.model?.image_format ?? 'webp') === fmt
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-transparent text-muted-foreground hover:text-foreground hover:bg-accent'
                    }`}
                  >
                    {fmt}
                  </button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                WebP is ~35% smaller; use JPEG for max compatibility.
              </p>
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">
                Image Quality
                <span className="ml-1.5 text-xs text-muted-foreground font-normal">
                  ({formData.model?.image_quality ?? 80})
                </span>
              </label>
              <div className="flex items-center gap-2 pt-1">
                <input
                  type="range"
                  min={1}
                  max={100}
                  step={1}
                  value={formData.model?.image_quality ?? 80}
                  onChange={(e) =>
                    setFormData((prev) => ({
                      ...prev,
                      model: { ...prev.model, image_quality: parseInt(e.target.value) },
                    }))
                  }
                  className="flex-1 accent-primary"
                />
              </div>
              <p className="text-xs text-muted-foreground">Lower = smaller payload, faster upload.</p>
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Concurrency</label>
              <Input
                type="number"
                min={1}
                max={16}
                step={1}
                value={formData.model?.concurrency ?? 1}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    model: {
                      ...prev.model,
                      concurrency: Math.max(1, Math.min(16, parseInt(e.target.value) || 1)),
                    },
                  }))
                }
                className="text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Parallel API requests (2–4 for local GPU batching).
              </p>
            </div>
          </div>

          <div className="flex items-center justify-between p-3 rounded-lg bg-accent/40 border border-border">
            <div className="space-y-0.5">
              <label className="text-sm font-medium text-foreground cursor-pointer">
                Structured JSON Outputs
              </label>
              <p className="text-xs text-muted-foreground">
                Enforce native JSON schema responses from supported model providers.
              </p>
            </div>
            <Switch
              checked={formData.model?.use_structured_outputs ?? true}
              onCheckedChange={(checked) =>
                setFormData((prev) => ({
                  ...prev,
                  model: { ...prev.model, use_structured_outputs: checked },
                }))
              }
            />
          </div>
          {/* Advanced OpenAI API Parameters */}
          <AdvancedApiParams
            params={advancedParams}
            enabledKeys={advancedEnabled}
            useStructuredOutputs={formData.model?.use_structured_outputs ?? true}
            onChange={(params, enabled) => {
              setAdvancedParams(params);
              setAdvancedEnabled(enabled);
            }}
          />
        </CardContent>
      </Card>

      {/* Section 3: System & User Prompt Textareas */}
      <Card className="border-border">
        <CardHeader>
          <div className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-primary" />
            <CardTitle>Prompt Templates</CardTitle>
          </div>
          <CardDescription>
            Customize system role instructions and prompt criteria sent to the vision model.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">System Prompt</label>
            <textarea
              value={formData.model?.params?.system_prompt || ''}
              onChange={(e) =>
                setFormData((prev) => ({
                  ...prev,
                  model: {
                    ...prev.model,
                    params: { ...prev.model?.params, system_prompt: e.target.value },
                  },
                }))
              }
              placeholder="You are an expert AI vision assistant..."
              rows={3}
              className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 font-mono"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">User Prompt / Tagging Instructions</label>
            <textarea
              value={formData.model?.params?.user_prompt || ''}
              onChange={(e) =>
                setFormData((prev) => ({
                  ...prev,
                  model: {
                    ...prev.model,
                    params: { ...prev.model?.params, user_prompt: e.target.value },
                  },
                }))
              }
              placeholder="Analyze the image and evaluate each target tag..."
              rows={3}
              className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 font-mono"
            />
          </div>
        </CardContent>
      </Card>

      {/* Section 4: Tag Definitions & Thresholds */}
      <Card className="border-border">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Sliders className="w-5 h-5 text-primary" />
            <CardTitle>Tag Definitions & Thresholds</CardTitle>
          </div>
          <CardDescription>
            Configure tags recognized during AI scanning and their confidence cutoffs.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Add New Tag Row */}
          <div className="p-4 rounded-lg bg-accent/30 border border-border space-y-3">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Add New Tag
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-12 gap-3 items-end">
              <div className="sm:col-span-4 space-y-1">
                <label className="text-xs font-medium">Tag Name</label>
                <Input
                  value={newTagName}
                  onChange={(e) => setNewTagName(e.target.value)}
                  placeholder="e.g. sunset"
                  className="text-sm"
                />
              </div>
              <div className="sm:col-span-5 space-y-1">
                <label className="text-xs font-medium">Description</label>
                <Input
                  value={newTagDesc}
                  onChange={(e) => setNewTagDesc(e.target.value)}
                  placeholder="Sun low on horizon, golden hour colors"
                  className="text-sm"
                />
              </div>
              <div className="sm:col-span-2 space-y-1">
                <label className="text-xs font-medium">Threshold</label>
                <Input
                  type="number"
                  step="0.05"
                  min="0"
                  max="1"
                  value={newTagThreshold}
                  onChange={(e) => setNewTagThreshold(parseFloat(e.target.value) || 0.7)}
                  className="text-sm"
                />
              </div>
              <div className="sm:col-span-1">
                <Button size="sm" onClick={handleAddTag} className="w-full gap-1">
                  <Plus className="w-4 h-4" />
                </Button>
              </div>
            </div>
          </div>

          {/* List of Existing Tags */}
          <div className="space-y-3">
            {Object.keys(formData.tags || {}).length === 0 ? (
              <div className="p-6 text-center text-muted-foreground border border-dashed rounded-lg">
                No tags defined yet. Add your first tag above.
              </div>
            ) : (
              Object.entries(formData.tags).map(([name, tag]) => (
                <div
                  key={name}
                  className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 p-3.5 rounded-lg border border-border bg-card hover:bg-accent/20 transition-colors"
                >
                  <div className="flex items-center gap-2 min-w-[140px]">
                    <Badge variant="secondary" className="font-semibold text-sm px-2.5 py-0.5">
                      {name}
                    </Badge>
                  </div>

                  <div className="flex-1 w-full sm:w-auto">
                    <Input
                      value={tag.description || ''}
                      onChange={(e) => handleUpdateTag(name, 'description', e.target.value)}
                      placeholder="Tag description..."
                      className="text-xs h-8"
                    />
                  </div>

                  <div className="flex items-center gap-3 shrink-0 w-full sm:w-auto justify-between sm:justify-end">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs text-muted-foreground">Min Score:</span>
                      <Input
                        type="number"
                        step="0.05"
                        min="0"
                        max="1"
                        value={tag.threshold ?? 0.7}
                        onChange={(e) =>
                          handleUpdateTag(name, 'threshold', parseFloat(e.target.value) || 0.7)
                        }
                        className="w-20 text-xs h-8"
                      />
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleRemoveTag(name)}
                      className="text-destructive hover:text-destructive hover:bg-destructive/10 h-8 w-8 p-0"
                      title="Delete tag"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default ConfigTab;
