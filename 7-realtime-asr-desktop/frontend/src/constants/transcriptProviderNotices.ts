export interface ProviderNoticeLink {
  label: string;
  href: string;
}

export interface ProviderNotice {
  title: string;
  summary: string;
  bullets: string[];
  links: ProviderNoticeLink[];
  footnote?: string;
}

export const CNN_STT_PROVIDER_NOTICE: ProviderNotice = {
  title: 'License & Attribution',
  summary:
    'The bundled CNN STT ONNX path in this app is based on the CNN STT base model and is suitable for commercial use with attribution.',
  bullets: [
    'Base model: <cnn-stt-base-model>',
    'Current ONNX bundle provenance: <cnn-stt-onnx-bundle>',
    'License: CC-BY-4.0',
    'Commercial use is allowed, but attribution should be included in Third-Party Notices / OSS Notices.',
  ],
  links: [
    {
      label: 'NVIDIA base model',
      href: '<cnn-stt-base-model-url>',
    },
    {
      label: 'Current ONNX conversion',
      href: '<cnn-stt-onnx-bundle-url>',
    },
    {
      label: 'CC-BY-4.0 license',
      href: 'https://creativecommons.org/licenses/by/4.0/',
    },
  ],
  footnote:
    'If you override RELAY_CNN_STT_ONNX_PATH with another model, verify that model\'s license separately before shipping.',
};
