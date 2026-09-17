import { useState, useEffect, useCallback } from 'react';
import { invoke as invokeTauri } from '@tauri-apps/api/core';
import Analytics from '@/lib/analytics';

export function useTemplates() {
  const [availableTemplates, setAvailableTemplates] = useState<Array<{
    id: string;
    name: string;
    description: string;
  }>>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<string>('standard_meeting');

  // Only the default ("standard_meeting") template is exposed in the UI —
  // template selection is intentionally hidden so every summary uses the
  // same baseline. The other JSON files in src-tauri/templates remain for
  // potential future use but are filtered out here.
  useEffect(() => {
    const fetchTemplates = async () => {
      try {
        const templates = await invokeTauri('api_list_templates') as Array<{
          id: string;
          name: string;
          description: string;
        }>;
        const defaultOnly = templates.filter((t) => t.id === 'standard_meeting');
        setAvailableTemplates(defaultOnly);
      } catch (error) {
        console.error('Failed to fetch templates:', error);
      }
    };
    fetchTemplates();
  }, []);

  const handleTemplateSelection = useCallback((templateId: string, _templateName: string) => {
    setSelectedTemplate(templateId);
    Analytics.trackFeatureUsed('template_selected');
  }, []);

  return {
    availableTemplates,
    selectedTemplate,
    handleTemplateSelection,
  };
}
