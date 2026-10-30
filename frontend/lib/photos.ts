import { asset } from "./site";

// Photos in /public/photos, from Wikimedia Commons. Their licences (CC BY / CC BY-SA) require this credit.
export interface PhotoCredit { title: string; author: string; license: string; source: string }

export const PHOTO_CREDITS: Record<string, PhotoCredit> = {
  "goa": { title: "Palolem Beach", author: "iMahesh", license: "CC BY-SA 4.0", source: "https://commons.wikimedia.org/wiki/File:Palolem_Beach,_South_Goa.jpg" },
  "jaipur": { title: "Hawa Mahal", author: "Chainwit.", license: "CC BY-SA 4.0", source: "https://commons.wikimedia.org/wiki/File:East_facade_Hawa_Mahal_Jaipur_from_ground_level_(July_2022)_-_img_01.jpg" },
  "udaipur": { title: "Lake Pichola", author: "Uri Sittan Tripo", license: "CC BY-SA 3.0", source: "https://commons.wikimedia.org/wiki/File:Udaipur_Lake_India.JPG" },
  "kerala": { title: "Kerala backwaters", author: "Augustus Binu", license: "CC BY-SA 3.0", source: "https://commons.wikimedia.org/wiki/File:House_Boat_DSW.jpg" },
  "manali": { title: "Solang Valley", author: "Harvinder Chandigarh", license: "CC BY-SA 4.0", source: "https://commons.wikimedia.org/wiki/File:Solang_Valley_,Manali,_Himachal_Pardes,_India.JPG" },
  "rishikesh": { title: "Lakshman Jhula", author: "KaustubhNayyar", license: "CC BY-SA 4.0", source: "https://commons.wikimedia.org/wiki/File:Rishikesh-Lakshman_Jhula_by_Kaustubh_Nayyar.jpg" },
  "leh": { title: "Leh Palace", author: "KennyOMG", license: "CC BY-SA 4.0", source: "https://commons.wikimedia.org/wiki/File:Leh_Palace_2011.jpg" },
  "varanasi": { title: "Dashashwamedh Ghat", author: "Saaremees", license: "CC BY-SA 4.0", source: "https://commons.wikimedia.org/wiki/File:Dasaswamedh_ghat-varanasi_india-andres_larin.jpg" },
  "andaman": { title: "Radhanagar Beach", author: "Harvinder Chandigarh", license: "CC BY-SA 4.0", source: "https://commons.wikimedia.org/wiki/File:Radha_Nagar_beach,_Havelock_Island,_Andamn,_India-_Sun_set_view.jpg" },
  "dubai": { title: "Burj Khalifa", author: "imran shahabuddin", license: "CC BY 2.0", source: "https://commons.wikimedia.org/wiki/File:Burj_Khalifa_(worlds_tallest_building)_and_the_Dubai_skyline_(25781049892).jpg" },
  "bangkok": { title: "Grand Palace", author: "Preecha.MJ", license: "CC BY-SA 4.0", source: "https://commons.wikimedia.org/wiki/File:0005574_-_Wat_Phra_Kaew_006.jpg" },
  "singapore": { title: "Marina Bay Sands", author: "Supanut Arunoprayote", license: "CC BY 4.0", source: "https://commons.wikimedia.org/wiki/File:Marina_Bay_Sands_(I).jpg" },
  "hero": { title: "Solang Valley", author: "Harvinder Chandigarh", license: "CC BY-SA 4.0", source: "https://commons.wikimedia.org/wiki/File:Solang_Valley_,Manali,_Himachal_Pardes,_India.JPG" },
};

/** Local photo for a destination name, if we ship one ("Goa" -> /photos/goa.jpg). */
export function destinationPhoto(name: string): string | null {
  const key = name.split(",")[0].trim().toLowerCase();
  return key in PHOTO_CREDITS && key !== "hero" ? asset(`/photos/${key}.jpg`) : null;
}
