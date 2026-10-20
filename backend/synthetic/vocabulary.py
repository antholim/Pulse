"""Word lists for synthetic Quebec data.

Organization names are built by combining common surnames, sectors and places,
so any resemblance to a real organization is a coincidence of common words.
"""

FIRST_NAMES = [
    "Émilie", "Marie-Ève", "Geneviève", "Chloé", "Léa", "Camille", "Sophie", "Julie",
    "Isabelle", "Mélanie", "Catherine", "Valérie", "Nathalie", "Audrey", "Josée",
    "Hélène", "Amélie", "Jessica", "Sarah", "Emily", "Olivia", "Fatima", "Amira",
    "François", "Jean-Philippe", "Mathieu", "Olivier", "Sébastien", "Étienne",
    "Guillaume", "Maxime", "Alexandre", "Nicolas", "Simon", "Félix", "Gabriel",
    "Louis", "Pierre-Luc", "Jérôme", "André", "Michael", "David", "James", "Daniel",
    "Karim", "Youssef", "Minh", "Wei", "Santiago", "Kwame",
]  # fmt: skip

LAST_NAMES = [
    "Tremblay", "Gagnon", "Roy", "Côté", "Bouchard", "Gauthier", "Morin", "Lavoie",
    "Fortin", "Gagné", "Ouellet", "Pelletier", "Bélanger", "Lévesque", "Bergeron",
    "Leblanc", "Paquette", "Girard", "Simard", "Boucher", "Caron", "Beaulieu",
    "Cloutier", "Dubé", "Poirier", "Fournier", "Lapointe", "Leclerc", "Lefebvre",
    "Poulin", "Thibault", "St-Pierre", "Nadeau", "Martin", "Landry", "Martel",
    "Bédard", "Grenier", "Lessard", "Bernier", "Richard", "Michaud", "Hébert",
    "Desjardins", "Couture", "Turcotte", "Lachance", "Parent", "Blais", "Gosselin",
    "Smith", "Johnson", "Nguyen", "Haddad", "Diallo", "Chen",
]  # fmt: skip

# (name, region) pairs used for addresses and place-based organization names.
CITIES = [
    ("Québec", "Capitale-Nationale"),
    ("Lévis", "Chaudière-Appalaches"),
    ("Saint-Georges", "Chaudière-Appalaches"),
    ("Baie-Saint-Paul", "Charlevoix"),
    ("La Malbaie", "Charlevoix"),
    ("Rimouski", "Bas-Saint-Laurent"),
    ("Rivière-du-Loup", "Bas-Saint-Laurent"),
    ("Sherbrooke", "Estrie"),
    ("Magog", "Estrie"),
    ("Granby", "Montérégie"),
    ("Trois-Rivières", "Mauricie"),
    ("Saguenay", "Saguenay-Lac-Saint-Jean"),
    ("Montmagny", "Chaudière-Appalaches"),
    ("Sainte-Marie", "Chaudière-Appalaches"),
]

# First letter of the postal code: G for eastern Quebec, J for the south and west.
POSTAL_PREFIX = {
    city: "J" if region in ("Estrie", "Montérégie") else "G" for city, region in CITIES
}

STREETS = [
    "rue Saint-Jean", "boulevard Laurier", "rue Saint-Joseph Est", "avenue Cartier",
    "chemin Sainte-Foy", "rue des Érables", "boulevard Charest Ouest", "rue King Ouest",
    "rue Principale", "avenue du Parc", "rue Racine", "boulevard Wilfrid-Hamel",
]  # fmt: skip

# Organization name patterns. {s} = surname, {c} = city, {s2} = second surname.
ORG_PATTERNS = [
    "Boulangerie {s}",
    "Groupe {s}",
    "Construction {s}",
    "Pharmacie {s}",
    "Garage {s} et fils",
    "Restaurant Chez {s}",
    "Cabinet {s} {s2}",
    "{s} & {s2} Avocats",
    "Technologies {s}",
    "{s} Technologies",
    "Coopérative de {c}",
    "Centre culturel de {c}",
    "Chambre de commerce de {c}",
    "Festival d'été de {c}",
    "Fondation {s}",
    "Clinique dentaire {s}",
    "Imprimerie {s}",
    "Transport {s}",
    "{c} Consulting",
    "Microbrasserie {s}",
]

# Organizations starting with these are institutions and carry no legal suffix.
INSTITUTION_PREFIXES = (
    "Coopérative",
    "Centre culturel",
    "Chambre de commerce",
    "Festival",
    "Fondation",
)

LEGAL_SUFFIXES = ["inc.", "ltée", "s.e.n.c.", "coop", "Inc.", "enr.", ""]

# Suffix variants a different source might use for the same organization.
SUFFIX_VARIANTS = {
    "inc.": ["Inc.", "inc", "INC.", ""],
    "Inc.": ["inc.", "Incorporated", ""],
    "ltée": ["Ltée", "limitée", "ltee", ""],
    "s.e.n.c.": ["senc", "S.E.N.C.", ""],
    "coop": ["Coop", "coopérative", ""],
    "enr.": ["Enr.", ""],
    "": ["inc.", ""],
}

TOP_LEVEL_DOMAINS = [".ca", ".qc.ca", ".com"]

JOB_TITLES = [
    "Directrice générale", "Directeur général", "Présidente", "Président",
    "Responsable des communications", "Directrice marketing", "Coordonnateur des événements",
    "Chargée de projet", "Propriétaire", "Conseiller", "Journaliste", "Chef de pupitre",
]  # fmt: skip

# Category names in French and English.
CATEGORIES = [
    ("Actualités", "News"),
    ("Affaires", "Business"),
    ("Culture", "Culture"),
    ("Sports", "Sports"),
    ("Société", "Society"),
    ("Santé", "Health"),
    ("Éducation", "Education"),
    ("Environnement", "Environment"),
    ("Gastronomie", "Food"),
    ("Tourisme", "Tourism"),
    ("Technologie", "Technology"),
    ("Communauté", "Community"),
]

EVENT_NAMES = [
    "Forum économique de {c}",
    "Soirée reconnaissance de {org}",
    "Salon de l'emploi de {c}",
    "Festival gourmand de {c}",
    "Conférence sur l'innovation à {c}",
    "Marché de Noël de {c}",
    "Gala annuel de {org}",
    "Journée portes ouvertes de {org}",
]

PROJECT_NAMES = [
    "Revitalisation du centre-ville de {c}",
    "Programme de mentorat de {org}",
    "Corridor vert de {c}",
    "Incubateur d'entreprises de {c}",
]
