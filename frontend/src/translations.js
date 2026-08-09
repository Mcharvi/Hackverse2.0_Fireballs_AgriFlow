// translations.js — UI strings for AgriFlow in English, Hindi, and Gujarati.
// The assistant answers questions in its own language regardless of UI lang;
// this only localizes the static interface labels.

export const LANGUAGES = {
  en: "English",
  hi: "हिन्दी",
  gu: "ગુજરાતી",
};

const en = {
  // Navbar
  simulateNewPlant: "Simulate a new plant",
  talkToAssistant: "AI Assistant",

  // Chat panel
  assistantHeading: "AgriFlow Assistant",
  newChat: "New chat",
  howCanIHelp: "How can I help you?",
  askInLanguages: "Ask about supply, plants, or routing — in English, Hindi, or Gujarati.",
  askAnythingPlaceholder: "Ask anything…",
  micAskTitle: "Ask by voice",
  micStopTitle: "Stop listening",
  micNotSupported: "Voice input isn't supported in this browser.",
  micBlocked: "Microphone access was blocked — allow it in your browser and try again.",
  suggestion1: "What is the nearest plant from Morbi?",
  suggestion2: "Which district produces the most residue?",
  suggestion3: "Which districts still have no matched plant?",
  suggestion4: "Which plants still have spare capacity?",

  // Explorer section
  explorerHeading: "Explore the numbers",
  explorerSubheading: "Predicted supply, plant matching, and what's left over — dive into each view.",
  tabSupply: "Predicted Supply",
  tabMatched: "Matched to Plants",
  tabPlants: "Plants",
  tabLeftover: "Leftover",
  supplyMeta: (total, count) =>
    `${total} units predicted across ${count} districts — the 2026 forecast extends official district APY residue (DES Agristat 2010–2022), projected iteratively 2024 → 2026, clipped ±15%.`,
  matchedMeta: (count, total) =>
    `${count} routes move ${total} units to plants — exact min-cost-flow matching, globally optimal haul distance.`,
  plantsMeta: (count) =>
    `${count} processing plants — utilization is load vs. annual capacity from the same matching run.`,
  leftoverMeta: (count, total) =>
    `${count} districts with ${total} units unserved — this is what would be burned without more plant capacity.`,
  leftoverEmpty: "No leftover supply — every district is matched.",

  // Explorer table columns
  colDistrict: "DISTRICT",
  colTier: "TIER",
  colPredictedSupply: "PREDICTED SUPPLY (2026)",
  colConfidence: "CONFIDENCE",
  colHarvestWindow: "HARVEST WINDOW",
  colResidue: "RESIDUE",
  colMatchedTo: "MATCHED TO",
  colAllocated: "ALLOCATED",
  colDistance: "DISTANCE",
  colPickupOrder: "PICKUP ORDER",
  colStatus: "STATUS",
  colPlant: "PLANT",
  colCapacity: "CAPACITY",
  colCurrentLoad: "CURRENT LOAD",
  colUtilization: "UTILIZATION",
  colRepDistrict: "REPRESENTATIVE DISTRICT",
};

const hi = {
  simulateNewPlant: "नया प्लांट जोड़ें",
  talkToAssistant: "AI सहायक",

  assistantHeading: "AgriFlow सहायक",
  newChat: "नई चैट",
  howCanIHelp: "मैं आपकी कैसे मदद करूं?",
  askInLanguages: "आपूर्ति, प्लांट या रूटिंग के बारे में पूछें — हिंदी, अंग्रेज़ी या गुजराती में।",
  askAnythingPlaceholder: "कुछ भी पूछें…",
  micAskTitle: "आवाज़ से पूछें",
  micStopTitle: "सुनना बंद करें",
  micNotSupported: "इस ब्राउज़र में आवाज़ इनपुट उपलब्ध नहीं है।",
  micBlocked: "माइक्रोफ़ोन एक्सेस ब्लॉक था — ब्राउज़र में अनुमति दें और फिर कोशिश करें।",
  suggestion1: "मोरबी से सबसे नज़दीकी प्लांट कौन सा है?",
  suggestion2: "किस जिले में सबसे ज़्यादा अवशेष उत्पादन होता है?",
  suggestion3: "किन जिलों का कोई मैचेड प्लांट नहीं है?",
  suggestion4: "किन प्लांट्स में अभी क्षमता बची है?",

  explorerHeading: "आंकड़े देखें",
  explorerSubheading: "अनुमानित आपूर्ति, प्लांट मिलान और बचा हुआ अवशेष — हर दृश्य देखें।",
  tabSupply: "अनुमानित आपूर्ति",
  tabMatched: "प्लांट से मिलान",
  tabPlants: "प्लांट",
  tabLeftover: "बचा हुआ",
  supplyMeta: (total, count) =>
    `${count} जिलों में ${total} यूनिट अनुमानित — 2026 का पूर्वानुमान आधिकारिक जिला APY अवशेष (DES Agristat 2010–2022) से, 2024 → 2026 तक क्रमिक प्रक्षेपण, ±15% सीमा तक।`,
  matchedMeta: (count, total) =>
    `${count} रूट से ${total} यूनिट प्लांट तक पहुंचती है — सटीक न्यूनतम-लागत मिलान, कुल ढुलाई दूरी के हिसाब से सर्वोत्तम।`,
  plantsMeta: (count) =>
    `${count} प्रोसेसिंग प्लांट — उपयोग दर लोड बनाम वार्षिक क्षमता है।`,
  leftoverMeta: (count, total) =>
    `${count} जिलों की ${total} यूनिट अधूरी है — अधिक प्लांट क्षमता के बिना यही जलाया जाएगा।`,
  leftoverEmpty: "कोई बचा हुआ अवशेष नहीं — हर जिला मिल चुका है।",

  colDistrict: "जिला",
  colTier: "स्तर",
  colPredictedSupply: "अनुमानित आपूर्ति (2026)",
  colConfidence: "विश्वसनीयता",
  colHarvestWindow: "कटाई अवधि",
  colResidue: "अवशेष",
  colMatchedTo: "मिलान",
  colAllocated: "आवंटित",
  colDistance: "दूरी",
  colPickupOrder: "पिकअप क्रम",
  colStatus: "स्थिति",
  colPlant: "प्लांट",
  colCapacity: "क्षमता",
  colCurrentLoad: "वर्तमान लोड",
  colUtilization: "उपयोग दर",
  colRepDistrict: "प्रतिनिधि जिला",
};

const gu = {
  simulateNewPlant: "નવો પ્લાન્ટ ઉમેરો",
  talkToAssistant: "AI સહાયક",

  assistantHeading: "AgriFlow સહાયક",
  newChat: "નવી ચેટ",
  howCanIHelp: "હું તમને કેવી રીતે મદદ કરી શકું?",
  askInLanguages: "પુરવઠો, પ્લાન્ટ કે રૂટીંગ વિશે પૂછો — ગુજરાતી, અંગ્રેજી કે હિન્દીમાં.",
  askAnythingPlaceholder: "કંઈપણ પૂછો…",
  micAskTitle: "અવાજથી પૂછો",
  micStopTitle: "સાંભળવાનું બંધ કરો",
  micNotSupported: "આ બ્રાઉઝરમાં અવાજ ઇનપુટ ઉપલબ્ધ નથી.",
  micBlocked: "માઇક્રોફોન એક્સેસ બ્લોક હતી — બ્રાઉઝરમાં પરવાનગી આપીને ફરી પ્રયત્ન કરો.",
  suggestion1: "મોરબીથી સૌથી નજીકનો પ્લાન્ટ કયો છે?",
  suggestion2: "કયા જિલ્લામાં સૌથી વધુ અવશેષ ઉત્પાદન થાય છે?",
  suggestion3: "કયા જિલ્લાઓનો કોઈ મેચ્ડ પ્લાન્ટ નથી?",
  suggestion4: "કયા પ્લાન્ટમાં હજુ ક્ષમતા બાકી છે?",

  explorerHeading: "આંકડા જુઓ",
  explorerSubheading: "અનુમાનિત પુરવઠો, પ્લાન્ટ મિલાન અને બાકી અવશેષ — દરેક દૃશ્ય જુઓ.",
  tabSupply: "અનુમાનિત પુરવઠો",
  tabMatched: "પ્લાન્ટ સાથે મિલાન",
  tabPlants: "પ્લાન્ટ",
  tabLeftover: "બાકી",
  supplyMeta: (total, count) =>
    `${count} જિલ્લામાં ${total} યુનિટ અનુમાનિત — 2026નો પૂર્વાનુમાન સત્તાવાર જિલ્લા APY અવશેષ (DES Agristat 2010–2022) થી, 2024 → 2026 સુધી ક્રમિક પ્રક્ષેપણ, ±15% મર્યાદા સુધી.`,
  matchedMeta: (count, total) =>
    `${count} રૂટ દ્વારા ${total} યુનિટ પ્લાન્ટ સુધી પહોંચે છે — ચોક્કસ ન્યૂનતમ-ખર્ચ મિલાન, કુલ પરિવહન અંતરની દૃષ્ટિએ શ્રેષ્ઠ.`,
  plantsMeta: (count) =>
    `${count} પ્રોસેસિંગ પ્લાન્ટ — ઉપયોગ દર એ લોડ વિરુદ્ધ વાર્ષિક ક્ષમતા છે.`,
  leftoverMeta: (count, total) =>
    `${count} જિલ્લાની ${total} યુનિટ અધૂરી છે — વધુ પ્લાન્ટ ક્ષમતા વિના આ જ બાળવામાં આવશે.`,
  leftoverEmpty: "કોઈ બાકી અવશેષ નથી — દરેક જિલ્લો મળી ગયો છે.",

  colDistrict: "જિલ્લો",
  colTier: "સ્તર",
  colPredictedSupply: "અનુમાનિત પુરવઠો (2026)",
  colConfidence: "વિશ્વસનીયતા",
  colHarvestWindow: "લણણી સમયગાળો",
  colResidue: "અવશેષ",
  colMatchedTo: "મિલાન",
  colAllocated: "ફાળવેલ",
  colDistance: "અંતર",
  colPickupOrder: "પિકઅપ ક્રમ",
  colStatus: "સ્થિતિ",
  colPlant: "પ્લાન્ટ",
  colCapacity: "ક્ષમતા",
  colCurrentLoad: "હાલનો લોડ",
  colUtilization: "ઉપયોગ દર",
  colRepDistrict: "પ્રતિનિધિ જિલ્લો",
};

export const translations = { en, hi, gu };
