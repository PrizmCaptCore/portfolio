import React, { useState, useEffect } from 'react';
import { Globe } from 'lucide-react';
import Analytics from '@/lib/analytics';
import { toast } from 'sonner';
import { useConfig } from '@/contexts/ConfigContext';

export interface Language {
  code: string;
  name: string;
}

// ISO 639-1 
const LANGUAGES: Language[] = [
  { code: 'auto', name: 'Auto Detect (Original Language)' },
  { code: 'auto-translate', name: 'Auto Detect (Translate to English)' },
  { code: 'en', name: 'English' },
  { code: 'zh', name: 'Chinese' },
  { code: 'de', name: 'German' },
  { code: 'es', name: 'Spanish' },
  { code: 'ru', name: 'Russian' },
  { code: 'ko', name: 'Korean' },
  { code: 'fr', name: 'French' },
  { code: 'ja', name: 'Japanese' },
  { code: 'pt', name: 'Portuguese' },
  { code: 'tr', name: 'Turkish' },
  { code: 'pl', name: 'Polish' },
  { code: 'ca', name: 'Catalan' },
  { code: 'nl', name: 'Dutch' },
  { code: 'ar', name: 'Arabic' },
  { code: 'sv', name: 'Swedish' },
  { code: 'it', name: 'Italian' },
  { code: 'id', name: 'Indonesian' },
  { code: 'hi', name: 'Hindi' },
  { code: 'fi', name: 'Finnish' },
  { code: 'vi', name: 'Vietnamese' },
  { code: 'he', name: 'Hebrew' },
  { code: 'uk', name: 'Ukrainian' },
  { code: 'el', name: 'Greek' },
  { code: 'ms', name: 'Malay' },
  { code: 'cs', name: 'Czech' },
  { code: 'ro', name: 'Romanian' },
  { code: 'da', name: 'Danish' },
  { code: 'hu', name: 'Hungarian' },
  { code: 'ta', name: 'Tamil' },
  { code: 'no', name: 'Norwegian' },
  { code: 'th', name: 'Thai' },
  { code: 'ur', name: 'Urdu' },
  { code: 'hr', name: 'Croatian' },
  { code: 'bg', name: 'Bulgarian' },
  { code: 'lt', name: 'Lithuanian' },
  { code: 'la', name: 'Latin' },
  { code: 'mi', name: 'Maori' },
  { code: 'ml', name: 'Malayalam' },
  { code: 'cy', name: 'Welsh' },
  { code: 'sk', name: 'Slovak' },
  { code: 'te', name: 'Telugu' },
  { code: 'fa', name: 'Persian' },
  { code: 'lv', name: 'Latvian' },
  { code: 'bn', name: 'Bengali' },
  { code: 'sr', name: 'Serbian' },
  { code: 'az', name: 'Azerbaijani' },
  { code: 'sl', name: 'Slovenian' },
  { code: 'kn', name: 'Kannada' },
  { code: 'et', name: 'Estonian' },
  { code: 'mk', name: 'Macedonian' },
  { code: 'br', name: 'Breton' },
  { code: 'eu', name: 'Basque' },
  { code: 'is', name: 'Icelandic' },
  { code: 'hy', name: 'Armenian' },
  { code: 'ne', name: 'Nepali' },
  { code: 'mn', name: 'Mongolian' },
  { code: 'bs', name: 'Bosnian' },
  { code: 'kk', name: 'Kazakh' },
  { code: 'sq', name: 'Albanian' },
  { code: 'sw', name: 'Swahili' },
  { code: 'gl', name: 'Galician' },
  { code: 'mr', name: 'Marathi' },
  { code: 'pa', name: 'Punjabi' },
  { code: 'si', name: 'Sinhala' },
  { code: 'km', name: 'Khmer' },
  { code: 'sn', name: 'Shona' },
  { code: 'yo', name: 'Yoruba' },
  { code: 'so', name: 'Somali' },
  { code: 'af', name: 'Afrikaans' },
  { code: 'oc', name: 'Occitan' },
  { code: 'ka', name: 'Georgian' },
  { code: 'be', name: 'Belarusian' },
  { code: 'tg', name: 'Tajik' },
  { code: 'sd', name: 'Sindhi' },
  { code: 'gu', name: 'Gujarati' },
  { code: 'am', name: 'Amharic' },
  { code: 'yi', name: 'Yiddish' },
  { code: 'lo', name: 'Lao' },
  { code: 'uz', name: 'Uzbek' },
  { code: 'fo', name: 'Faroese' },
  { code: 'ht', name: 'Haitian Creole' },
  { code: 'ps', name: 'Pashto' },
  { code: 'tk', name: 'Turkmen' },
  { code: 'nn', name: 'Norwegian Nynorsk' },
  { code: 'mt', name: 'Maltese' },
  { code: 'sa', name: 'Sanskrit' },
  { code: 'lb', name: 'Luxembourgish' },
  { code: 'my', name: 'Myanmar' },
  { code: 'bo', name: 'Tibetan' },
  { code: 'tl', name: 'Tagalog' },
  { code: 'mg', name: 'Malagasy' },
  { code: 'as', name: 'Assamese' },
  { code: 'tt', name: 'Tatar' },
  { code: 'haw', name: 'Hawaiian' },
  { code: 'ln', name: 'Lingala' },
  { code: 'ha', name: 'Hausa' },
  { code: 'ba', name: 'Bashkir' },
  { code: 'jw', name: 'Javanese' },
  { code: 'su', name: 'Sundanese' },
];

interface LanguageSelectionProps {
  selectedLanguage: string;
  onLanguageChange: (language: string) => void;
  disabled?: boolean;
  provider?: 'cnn-stt' | 'deepgram' | 'elevenLabs' | 'groq' | 'openai';
}

export function LanguageSelection({
  selectedLanguage,
  onLanguageChange,
  disabled = false,
  provider = 'cnn-stt'
}: LanguageSelectionProps) {
  const [saving, setSaving] = useState(false);
  const { setSelectedLanguage } = useConfig();

  // CNN STT only supports auto-detection (doesn't support manual language selection)
  const isCNN STT = provider === 'cnn-stt';
  const availableLanguages = isCNN STT
    ? LANGUAGES.filter(lang => lang.code === 'auto' || lang.code === 'auto-translate')
    : LANGUAGES;

  const handleLanguageChange = async (languageCode: string) => {
    setSaving(true);
    try {
      // Save language preference to localStorage and sync to backend
      setSelectedLanguage(languageCode);
      onLanguageChange(languageCode);
      console.log('Language preference saved:', languageCode);

      // Track language selection analytics
      const selectedLang = LANGUAGES.find(lang => lang.code === languageCode);
      await Analytics.track('language_selected', {
        language_code: languageCode,
        language_name: selectedLang?.name || 'Unknown',
        is_auto_detect: (languageCode === 'auto').toString(),
        is_auto_translate: (languageCode === 'auto-translate').toString()
      });

      // Show success toast
      const languageName = selectedLang?.name || languageCode;
      toast.success("언어 환경설정을 저장했습니다", {
        description: `전사 언어를 ${languageName}(으)로 설정했습니다`
      });
    } catch (error) {
      console.error('Failed to save language preference:', error);
      toast.error("언어 환경설정을 저장하지 못했습니다", {
        description: error instanceof Error ? error.message : String(error)
      });
    } finally {
      setSaving(false);
    }
  };

  // Find the selected language name for display
  const selectedLanguageName = LANGUAGES.find(
    lang => lang.code === selectedLanguage
  )?.name || '자동 감지 (원본 언어)';

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Globe className="h-4 w-4 text-gray-600" />
          <h4 className="text-sm font-medium text-gray-900">전사 언어</h4>
        </div>
      </div>

      <div className="space-y-2">
        <select
          value={selectedLanguage}
          onChange={(e) => handleLanguageChange(e.target.value)}
          disabled={disabled || saving}
          className="w-full px-3 py-2 text-sm bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-50 disabled:text-gray-500"
        >
          {availableLanguages.map((language) => (
            <option key={language.code} value={language.code}>
              {language.name}
              {language.code !== 'auto' && language.code !== 'auto-translate' && ` (${language.code})`}
            </option>
          ))}
        </select>

        {/* CNN STT language limitation warning */}
        {isCNN STT && (
          <div className="p-2 bg-amber-50 border border-amber-200 rounded text-amber-800">
            <p className="font-medium">ℹ CNN STT 언어 지원</p>
            <p className="mt-1 text-xs">CNN STT은 현재 자동 언어 감지만 지원합니다. 특정 언어를 지정해야 한다면 Whisper를 사용해 주세요.</p>
          </div>
        )}

        {/* Info text */}
        <div className="text-xs space-y-2 pt-2">
          <p className="text-gray-600">
            <strong>현재 설정:</strong> {selectedLanguageName}
          </p>
          {selectedLanguage === 'auto' && (
            <div className="p-2 bg-yellow-50 border border-yellow-200 rounded text-yellow-800">
              <p className="font-medium"> 자동 감지는 부정확할 수 있습니다</p>
              <p className="mt-1">정확도를 높이려면 특정 언어를 선택해 주세요 (예: 한국어, 영어 등)</p>
            </div>
          )}
          {selectedLanguage === 'auto-translate' && (
            <div className="p-2 bg-blue-50 border border-blue-200 rounded text-blue-800">
              <p className="font-medium"> 번역 모드 사용 중</p>
              <p className="mt-1">모든 오디오가 자동으로 영어로 번역됩니다. 다국어 회의에서 영문 결과가 필요할 때 적합합니다.</p>
            </div>
          )}
          {selectedLanguage !== 'auto' && selectedLanguage !== 'auto-translate' && (
            <p className="text-gray-600">
              <strong>{selectedLanguageName}</strong>에 맞춰 전사가 최적화됩니다
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
