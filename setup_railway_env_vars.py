"""
Script pour générer les variables d'environnement Railway
pour le système dual Voyageur/Ménage
"""

import json
import os

def load_json_file(filepath):
    """Charger un fichier JSON"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Erreur lors du chargement de {filepath}: {e}")
        return None

def generate_env_var_value(data):
    """Convertir un dict en string JSON compact pour variable d'environnement"""
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))

def main():
    print("🚀 GÉNÉRATION DES VARIABLES D'ENVIRONNEMENT RAILWAY")
    print("=" * 80)
    
    # Fichiers de configuration
    configs = {
        "PROMPTS_CONFIG_VOYAGEUR": "front/prompts-config-voyageur.json",
        "PROMPTS_CONFIG_MENAGE": "front/prompts-config-menage.json",
        "ROOM_TEMPLATES_CONFIG_VOYAGEUR": "room_classfication/room-verification-templates-voyageur.json",
        "ROOM_TEMPLATES_CONFIG_MENAGE": "room_classfication/room-verification-templates-menage.json",
        "SCORING_CONFIG_VOYAGEUR": "front/scoring-config-voyageur.json",
        "SCORING_CONFIG_MENAGE": "front/scoring-config-menage.json"
    }
    
    # Générer les variables d'environnement
    env_vars = {}
    
    for var_name, filepath in configs.items():
        print(f"\n📄 Traitement de {var_name}...")
        print(f"   Fichier source : {filepath}")
        
        if not os.path.exists(filepath):
            print(f"   ⚠️  Fichier non trouvé : {filepath}")
            continue
        
        data = load_json_file(filepath)
        if data is None:
            continue
        
        env_value = generate_env_var_value(data)
        env_vars[var_name] = env_value
        
        print(f"   ✅ Variable générée ({len(env_value)} caractères)")
    
    # Sauvegarder dans un fichier .env pour référence
    print("\n" + "=" * 80)
    print("💾 Sauvegarde dans railway_env_vars.txt...")
    
    with open("railway_env_vars.txt", "w", encoding="utf-8") as f:
        f.write("# Variables d'environnement Railway pour le système dual Voyageur/Ménage\n")
        f.write("# Généré automatiquement - NE PAS MODIFIER MANUELLEMENT\n")
        f.write(f"# Date : {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("\n" + "=" * 80 + "\n\n")
        
        for var_name, var_value in env_vars.items():
            f.write(f"# {var_name}\n")
            f.write(f"{var_name}={var_value}\n\n")
    
    print("✅ Fichier railway_env_vars.txt créé avec succès !")
    
    # Afficher les instructions
    print("\n" + "=" * 80)
    print("📋 INSTRUCTIONS POUR RAILWAY")
    print("=" * 80)
    print("\n1. Connectez-vous à Railway : https://railway.app/")
    print("2. Sélectionnez votre projet CheckEasy API V5")
    print("3. Allez dans l'onglet 'Variables'")
    print("4. Ajoutez ou mettez à jour les variables suivantes :\n")
    
    for var_name in env_vars.keys():
        print(f"   ✅ {var_name}")
    
    print("\n5. Copiez les valeurs depuis le fichier 'railway_env_vars.txt'")
    print("6. Redéployez le service (Railway le fera automatiquement)")
    print("7. Attendez que le déploiement soit terminé")
    print("8. Lancez le script de test : python test_deployment_voyageur.py")
    
    print("\n" + "=" * 80)
    print("📊 RÉSUMÉ")
    print("=" * 80)
    print(f"\n✅ {len(env_vars)} variables d'environnement générées")
    print("✅ Fichier railway_env_vars.txt créé")
    print("\n🎯 Prochaine étape : Configurer les variables sur Railway")
    
    # Afficher un aperçu des tailles
    print("\n📏 Taille des variables :")
    for var_name, var_value in env_vars.items():
        size_kb = len(var_value) / 1024
        print(f"   {var_name}: {size_kb:.2f} KB")

if __name__ == "__main__":
    main()

