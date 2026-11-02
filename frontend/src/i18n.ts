import { createContext, useContext } from "react";

import type { LanguageCode } from "./types/api";

/**
 * UI strings. Hindi and Kannada are DRAFT translations (like the legal glossary): they need
 * native-speaker review before real use. Answers themselves come translated from the backend.
 */
const en = {
  askHeading: "Ask a question",
  questionLabel: "Your question (English, हिन्दी, ಕನ್ನಡ)",
  placeholder: "e.g. What are the grounds for divorce under the Hindu Marriage Act?",
  language: "Language",
  auto: "Auto-detect",
  ask: "Ask",
  speak: "🎤 Speak",
  stopRecording: "■ Stop recording",
  transcribing: "Transcribing…",
  listening: "Listening… it sends your question when you pause.",
  listen: "🔊 Listen",
  stopReading: "■ Stop reading",
  showEnglish: "Show English original",
  showTranslation: "Show translation",
  newConversation: "New conversation",
  followUpNote: "Follow-up questions use this conversation. Starting a new one deletes it.",
  starting: "Starting…",
  howMade: "How this answer was made",
  notCited: "(retrieved, not cited)",
  uncited: "This answer cites no sources. Treat it with caution.",
  sources: "Sources",
  chooseOne: "Choose one",
  helpful: "Helpful",
  notHelpful: "Not helpful",
  thanks: "Thanks for the feedback.",
  copy: "Copy",
  copied: "Copied",
  welcomeTitle: "Ask about Indian family law",
  welcomeText:
    "Type or speak in English, Hindi or Kannada. Answers are based on the Hindu Marriage Act, 1955 and court judgments, with numbered sources you can check.",
  examplesTitle: "Try asking",
  helpTitle: "Need help now?",
  helpEmergency: "Emergency: 112",
  helpWomen: "Women helpline: 181",
  helpLegalAid: "Free legal aid (NALSA): 15100",
  modelsLoading: "The models are still loading (about 2 minutes after the server starts). You can ask now; the answer will come once they are ready.",
  progress: {
    translate_query: "Translating your question…",
    understand: "Understanding your question…",
    retrieve_1: "Searching the law and judgments…",
    assess: "Checking the evidence…",
    retrieve_2: "Searching again for missing information…",
    generate: "Writing and verifying the answer…",
    translate_answer: "Translating the answer…",
  } as Record<string, string>,
};

export type Strings = typeof en;

const hi: Strings = {
  askHeading: "प्रश्न पूछें",
  questionLabel: "आपका प्रश्न (English, हिन्दी, ಕನ್ನಡ)",
  placeholder: "उदाहरण: क्या मैं क्रूरता के आधार पर तलाक ले सकती हूँ?",
  language: "भाषा",
  auto: "स्वतः पहचानें",
  ask: "पूछें",
  speak: "🎤 बोलें",
  stopRecording: "■ रिकॉर्डिंग रोकें",
  transcribing: "लिखा जा रहा है…",
  listening: "सुन रहा है… आपके रुकते ही सवाल भेज देगा।",
  listen: "🔊 सुनें",
  stopReading: "■ पढ़ना रोकें",
  showEnglish: "अंग्रेज़ी मूल दिखाएँ",
  showTranslation: "अनुवाद दिखाएँ",
  newConversation: "नई बातचीत",
  followUpNote: "आगे के प्रश्न इसी बातचीत को ध्यान में रखते हैं। नई बातचीत शुरू करने पर यह मिट जाएगी।",
  starting: "शुरू हो रहा है…",
  howMade: "यह उत्तर कैसे बना",
  notCited: "(मिला, पर उद्धृत नहीं)",
  uncited: "यह उत्तर किसी स्रोत का हवाला नहीं देता। सावधानी से लें।",
  sources: "स्रोत",
  chooseOne: "एक चुनें",
  helpful: "उपयोगी",
  notHelpful: "उपयोगी नहीं",
  thanks: "प्रतिक्रिया के लिए धन्यवाद।",
  copy: "कॉपी करें",
  copied: "कॉपी हो गया",
  welcomeTitle: "भारतीय पारिवारिक कानून के बारे में पूछें",
  welcomeText:
    "अंग्रेज़ी, हिंदी या कन्नड़ में लिखें या बोलें। उत्तर हिंदू विवाह अधिनियम, 1955 और अदालती फ़ैसलों पर आधारित होते हैं, और हर बात का क्रमांकित स्रोत दिया जाता है जिसे आप जाँच सकते हैं।",
  examplesTitle: "ये पूछकर देखें",
  helpTitle: "तुरंत मदद चाहिए?",
  helpEmergency: "आपातकाल: 112",
  helpWomen: "महिला हेल्पलाइन: 181",
  helpLegalAid: "निःशुल्क कानूनी सहायता (NALSA): 15100",
  modelsLoading: "मॉडल अभी लोड हो रहे हैं (सर्वर शुरू होने के लगभग 2 मिनट बाद तैयार)। आप अभी पूछ सकते हैं; तैयार होते ही उत्तर मिलेगा।",
  progress: {
    translate_query: "आपके प्रश्न का अनुवाद हो रहा है…",
    understand: "आपका प्रश्न समझा जा रहा है…",
    retrieve_1: "कानून और फ़ैसलों में खोज हो रही है…",
    assess: "स्रोतों की जाँच हो रही है…",
    retrieve_2: "छूटी जानकारी के लिए फिर से खोज हो रही है…",
    generate: "उत्तर लिखा और जाँचा जा रहा है…",
    translate_answer: "उत्तर का अनुवाद हो रहा है…",
  },
};

const kn: Strings = {
  askHeading: "ಪ್ರಶ್ನೆ ಕೇಳಿ",
  questionLabel: "ನಿಮ್ಮ ಪ್ರಶ್ನೆ (English, हिन्दी, ಕನ್ನಡ)",
  placeholder: "ಉದಾ: ಹಿಂದೂ ವಿವಾಹ ಕಾಯ್ದೆಯ ಅಡಿಯಲ್ಲಿ ವಿಚ್ಛೇದನಕ್ಕೆ ಆಧಾರಗಳು ಯಾವುವು?",
  language: "ಭಾಷೆ",
  auto: "ಸ್ವಯಂ ಗುರುತಿಸು",
  ask: "ಕೇಳಿ",
  speak: "🎤 ಮಾತನಾಡಿ",
  stopRecording: "■ ರೆಕಾರ್ಡಿಂಗ್ ನಿಲ್ಲಿಸಿ",
  transcribing: "ಬರೆಯಲಾಗುತ್ತಿದೆ…",
  listening: "ಆಲಿಸುತ್ತಿದೆ… ನೀವು ನಿಲ್ಲಿಸಿದಾಗ ಪ್ರಶ್ನೆಯನ್ನು ಕಳುಹಿಸುತ್ತದೆ.",
  listen: "🔊 ಕೇಳಿಸಿ",
  stopReading: "■ ಓದುವುದನ್ನು ನಿಲ್ಲಿಸಿ",
  showEnglish: "ಇಂಗ್ಲಿಷ್ ಮೂಲ ತೋರಿಸಿ",
  showTranslation: "ಅನುವಾದ ತೋರಿಸಿ",
  newConversation: "ಹೊಸ ಸಂಭಾಷಣೆ",
  followUpNote: "ಮುಂದಿನ ಪ್ರಶ್ನೆಗಳು ಈ ಸಂಭಾಷಣೆಯನ್ನು ಬಳಸುತ್ತವೆ. ಹೊಸದನ್ನು ಆರಂಭಿಸಿದರೆ ಇದು ಅಳಿಸಲಾಗುತ್ತದೆ.",
  starting: "ಆರಂಭವಾಗುತ್ತಿದೆ…",
  howMade: "ಈ ಉತ್ತರ ಹೇಗೆ ತಯಾರಾಯಿತು",
  notCited: "(ಸಿಕ್ಕಿದೆ, ಉಲ್ಲೇಖಿಸಿಲ್ಲ)",
  uncited: "ಈ ಉತ್ತರ ಯಾವುದೇ ಮೂಲವನ್ನು ಉಲ್ಲೇಖಿಸುವುದಿಲ್ಲ. ಎಚ್ಚರಿಕೆಯಿಂದ ಪರಿಗಣಿಸಿ.",
  sources: "ಮೂಲಗಳು",
  chooseOne: "ಒಂದನ್ನು ಆರಿಸಿ",
  helpful: "ಉಪಯುಕ್ತ",
  notHelpful: "ಉಪಯುಕ್ತವಲ್ಲ",
  thanks: "ಪ್ರತಿಕ್ರಿಯೆಗೆ ಧನ್ಯವಾದಗಳು.",
  copy: "ನಕಲಿಸಿ",
  copied: "ನಕಲಿಸಲಾಗಿದೆ",
  welcomeTitle: "ಭಾರತೀಯ ಕುಟುಂಬ ಕಾನೂನಿನ ಬಗ್ಗೆ ಕೇಳಿ",
  welcomeText:
    "ಇಂಗ್ಲಿಷ್, ಹಿಂದಿ ಅಥವಾ ಕನ್ನಡದಲ್ಲಿ ಟೈಪ್ ಮಾಡಿ ಅಥವಾ ಮಾತನಾಡಿ. ಉತ್ತರಗಳು ಹಿಂದೂ ವಿವಾಹ ಕಾಯ್ದೆ, 1955 ಮತ್ತು ನ್ಯಾಯಾಲಯದ ತೀರ್ಪುಗಳನ್ನು ಆಧರಿಸಿವೆ; ನೀವು ಪರಿಶೀಲಿಸಬಹುದಾದ ಸಂಖ್ಯೆಯ ಮೂಲಗಳೊಂದಿಗೆ.",
  examplesTitle: "ಹೀಗೆ ಕೇಳಿ ನೋಡಿ",
  helpTitle: "ತಕ್ಷಣ ಸಹಾಯ ಬೇಕೇ?",
  helpEmergency: "ತುರ್ತು: 112",
  helpWomen: "ಮಹಿಳಾ ಸಹಾಯವಾಣಿ: 181",
  helpLegalAid: "ಉಚಿತ ಕಾನೂನು ನೆರವು (NALSA): 15100",
  modelsLoading: "ಮಾದರಿಗಳು ಇನ್ನೂ ಲೋಡ್ ಆಗುತ್ತಿವೆ (ಸರ್ವರ್ ಆರಂಭವಾದ ಸುಮಾರು 2 ನಿಮಿಷಗಳ ನಂತರ ಸಿದ್ಧ). ನೀವು ಈಗಲೇ ಕೇಳಬಹುದು; ಸಿದ್ಧವಾದ ತಕ್ಷಣ ಉತ್ತರ ಬರುತ್ತದೆ.",
  progress: {
    translate_query: "ನಿಮ್ಮ ಪ್ರಶ್ನೆಯನ್ನು ಅನುವಾದಿಸಲಾಗುತ್ತಿದೆ…",
    understand: "ನಿಮ್ಮ ಪ್ರಶ್ನೆಯನ್ನು ಅರ್ಥಮಾಡಿಕೊಳ್ಳಲಾಗುತ್ತಿದೆ…",
    retrieve_1: "ಕಾನೂನು ಮತ್ತು ತೀರ್ಪುಗಳಲ್ಲಿ ಹುಡುಕಲಾಗುತ್ತಿದೆ…",
    assess: "ಆಧಾರಗಳನ್ನು ಪರಿಶೀಲಿಸಲಾಗುತ್ತಿದೆ…",
    retrieve_2: "ಕೊರತೆಯ ಮಾಹಿತಿಗಾಗಿ ಮತ್ತೆ ಹುಡುಕಲಾಗುತ್ತಿದೆ…",
    generate: "ಉತ್ತರವನ್ನು ಬರೆದು ಪರಿಶೀಲಿಸಲಾಗುತ್ತಿದೆ…",
    translate_answer: "ಉತ್ತರವನ್ನು ಅನುವಾದಿಸಲಾಗುತ್ತಿದೆ…",
  },
};

export const STRINGS: Record<LanguageCode, Strings> = { en, hi, kn };

/** Example questions (questions only: answers always come from the sources). */
export const EXAMPLES: Record<LanguageCode, string[]> = {
  en: [
    "What are the grounds for divorce under the Hindu Marriage Act?",
    "Can a wife claim maintenance while the divorce case is pending?",
    "Who decides custody of children during a divorce case?",
  ],
  hi: [
    "क्या मैं क्रूरता के आधार पर तलाक ले सकती हूँ?",
    "आपसी सहमति से तलाक कैसे होता है?",
    "घरेलू हिंसा होने पर मैं क्या कर सकती हूँ?",
  ],
  kn: [
    "ಹಿಂದೂ ವಿವಾಹ ಕಾಯ್ದೆಯ ಅಡಿಯಲ್ಲಿ ವಿಚ್ಛೇದನಕ್ಕೆ ಆಧಾರಗಳು ಯಾವುವು?",
    "ವಿಚ್ಛೇದನದ ಸಮಯದಲ್ಲಿ ಮಕ್ಕಳ ಪಾಲನೆಯ ಬಗ್ಗೆ ಯಾರು ನಿರ್ಧರಿಸುತ್ತಾರೆ?",
    "ಪರಸ್ಪರ ಒಪ್ಪಿಗೆಯಿಂದ ವಿಚ್ಛೇದನ ಪಡೆಯುವುದು ಹೇಗೆ?",
  ],
};

export const I18nContext = createContext<Strings>(en);

export function useT(): Strings {
  return useContext(I18nContext);
}
