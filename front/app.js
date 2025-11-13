/**
 * CheckEasy - Gestionnaire de Prompts IA
 * Application JavaScript principale
 */

class PromptManager {
    constructor() {
        this.prompts = {};
        this.originalPrompts = {};
        this.modifiedSections = new Set();
        this.currentSection = 'overview';
        this.currentParcoursType = 'Voyageur'; // Type de parcours actuel

        this.init();
    }

    async init() {
        try {
            await this.loadPrompts();
            this.setupEventListeners();
            this.renderOverview();
            this.renderAllEditors();
            this.showNotification('Interface chargée avec succès', 'success');
        } catch (error) {
            console.error('Erreur lors de l\'initialisation:', error);
            this.showNotification('Erreur lors du chargement de l\'interface', 'error');
        }
    }

    async loadPrompts() {
        try {
            // Charger depuis l'API avec le type de parcours
            const response = await fetch(`/prompts?type=${this.currentParcoursType}`);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const apiResponse = await response.json();
            if (apiResponse.success && apiResponse.config) {
                this.prompts = apiResponse.config;
                this.originalPrompts = JSON.parse(JSON.stringify(apiResponse.config)); // Deep copy
                this.showNotification(`Configuration des prompts ${this.currentParcoursType} chargée avec succès`, 'success');
                this.updateParcoursIndicator();
            } else {
                throw new Error('Format de réponse API invalide');
            }
        } catch (error) {
            console.error('Erreur lors du chargement des prompts:', error);
            // Fallback vers des données par défaut
            this.prompts = this.getDefaultPrompts();
            this.originalPrompts = JSON.parse(JSON.stringify(this.prompts));
            this.showNotification('Données par défaut chargées (impossible de charger depuis l\'API)', 'warning');
        }
    }

    updateParcoursIndicator() {
        const header = document.querySelector('.logo-section h1');
        const typeEmoji = this.currentParcoursType === 'Voyageur' ? '🧳' : '🧹';
        header.textContent = `CheckEasy - Gestionnaire de Prompts IA - ${typeEmoji} ${this.currentParcoursType}`;
    }

    getDefaultPrompts() {
        return {
            version: "1.0.0",
            last_updated: new Date().toISOString().split('T')[0],
            description: "Configuration des prompts pour CheckEasy API V5",
            prompts: {
                analyze_main: {
                    name: "Analyse Principale des Pièces",
                    description: "Prompt principal pour l'analyse comparative des images de pièces",
                    endpoint: "/analyze, /analyze-with-classification, /analyze-complete",
                    variables: ["commentaire_ia", "elements_critiques", "points_ignorables", "defauts_frequents", "piece_nom"],
                    sections: {
                        reset_header: "🔄 RESET COMPLET - NOUVELLE ANALYSE INDÉPENDANTE 🔄",
                        role_definition: "Tu es un expert en inspection de propreté...",
                        focus_principal: "FOCUS PRINCIPAL : ..."
                    }
                }
            },
            user_messages: {}
        };
    }

    setupEventListeners() {
        // Navigation
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                const section = e.currentTarget.dataset.section;
                this.navigateToSection(section);
            });
        });

        // Changement de type de parcours
        document.getElementById('parcoursTypeSelector').addEventListener('change', async (e) => {
            this.currentParcoursType = e.target.value;
            await this.loadPrompts();
            this.renderOverview();
            this.renderAllEditors();
        });

        // Actions du header
        document.getElementById('saveAllBtn').addEventListener('click', () => this.saveAll());
        document.getElementById('exportBtn').addEventListener('click', () => this.exportJson());
        document.getElementById('importBtn').addEventListener('click', () => this.triggerImport());
        document.getElementById('importFile').addEventListener('change', (e) => this.importJson(e));

        // Prévisualisation
        document.getElementById('generatePreview').addEventListener('click', () => this.generatePreview());
        document.getElementById('previewPromptSelect').addEventListener('change', () => this.updatePreviewVariables());

        // Raccourcis clavier
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey || e.metaKey) {
                if (e.key === 's') {
                    e.preventDefault();
                    this.saveAll();
                }
            }
        });
    }

    navigateToSection(sectionName) {
        // Mettre à jour la navigation
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.remove('active');
        });
        document.querySelector(`[data-section="${sectionName}"]`).classList.add('active');

        // Afficher la section
        document.querySelectorAll('.content-section').forEach(section => {
            section.classList.remove('active');
        });
        document.getElementById(sectionName).classList.add('active');

        this.currentSection = sectionName;

        // Actions spéciales pour certaines sections
        if (sectionName === 'overview') {
            this.renderOverview();
        } else if (sectionName === 'preview') {
            this.updatePreviewPromptSelect();
        }
    }

    renderOverview() {
        // Statistiques
        const totalPrompts = Object.keys(this.prompts.prompts || {}).length;
        const totalUserMessages = Object.keys(this.prompts.user_messages || {}).length;
        let totalSections = 0;
        
        Object.values(this.prompts.prompts || {}).forEach(prompt => {
            totalSections += Object.keys(prompt.sections || {}).length;
        });

        document.getElementById('totalPrompts').textContent = totalPrompts;
        document.getElementById('totalUserMessages').textContent = totalUserMessages;
        document.getElementById('totalSections').textContent = totalSections;
        document.getElementById('unsavedChanges').textContent = this.modifiedSections.size;

        // Liste des prompts
        this.renderPromptsList();
    }

    renderPromptsList() {
        const container = document.getElementById('promptsList');
        container.innerHTML = '';

        Object.entries(this.prompts.prompts || {}).forEach(([key, prompt]) => {
            const card = document.createElement('div');
            card.className = 'prompt-card';
            
            const hasModifications = Array.from(this.modifiedSections).some(section => section.startsWith(key));
            const status = hasModifications ? 'modified' : 'active';
            const statusText = hasModifications ? 'Modifié' : 'Actif';

            card.innerHTML = `
                <div class="prompt-card-header">
                    <div>
                        <h4>${prompt.name}</h4>
                        <p>${prompt.description}</p>
                        <div class="prompt-meta">
                            <span class="endpoint-tag">${prompt.endpoint}</span>
                        </div>
                    </div>
                    <span class="prompt-status ${status}">${statusText}</span>
                </div>
                <div class="prompt-variables">
                    ${(prompt.variables || []).map(variable => 
                        `<span class="variable-tag">{${variable}}</span>`
                    ).join('')}
                </div>
            `;

            card.addEventListener('click', () => {
                this.navigateToSection(key);
            });

            container.appendChild(card);
        });

        // Ajouter les messages utilisateur
        Object.entries(this.prompts.user_messages || {}).forEach(([key, message]) => {
            const card = document.createElement('div');
            card.className = 'prompt-card';
            
            card.innerHTML = `
                <div class="prompt-card-header">
                    <div>
                        <h4>${message.name}</h4>
                        <p>${message.description}</p>
                        <div class="prompt-meta">
                            <span class="endpoint-tag">${message.endpoint}</span>
                        </div>
                    </div>
                    <span class="prompt-status active">Message</span>
                </div>
                <div class="prompt-variables">
                    ${(message.variables || []).map(variable => 
                        `<span class="variable-tag">{${variable}}</span>`
                    ).join('')}
                </div>
            `;

            card.addEventListener('click', () => {
                this.navigateToSection('user_messages');
            });

            container.appendChild(card);
        });
    }

    renderAllEditors() {
        // Éditeurs pour les prompts principaux
        Object.entries(this.prompts.prompts || {}).forEach(([key, prompt]) => {
            this.renderPromptEditor(key, prompt);
        });

        // Éditeur pour les messages utilisateur
        this.renderUserMessagesEditor();
    }

    renderPromptEditor(promptKey, prompt) {
        const container = document.getElementById(`${promptKey}_editor`);
        if (!container) return;

        container.innerHTML = '';

        Object.entries(prompt.sections || {}).forEach(([sectionKey, content]) => {
            const sectionEditor = this.createSectionEditor(promptKey, sectionKey, content);
            container.appendChild(sectionEditor);
        });
    }

    createSectionEditor(promptKey, sectionKey, content) {
        const section = document.createElement('div');
        section.className = 'section-editor';
        section.dataset.promptKey = promptKey;
        section.dataset.sectionKey = sectionKey;

        const fullKey = `${promptKey}.${sectionKey}`;

        section.innerHTML = `
            <div class="section-editor-header">
                <h3>
                    <i class="fas fa-edit"></i>
                    ${this.formatSectionName(sectionKey)}
                </h3>
                <div class="section-actions">
                    <button class="btn btn-sm btn-secondary" onclick="promptManager.resetSection('${fullKey}')">
                        <i class="fas fa-undo"></i> Réinitialiser
                    </button>
                </div>
            </div>
            <textarea 
                data-section="${fullKey}"
                placeholder="Entrez le contenu de cette section..."
                rows="10"
            >${content}</textarea>
        `;

        const textarea = section.querySelector('textarea');
        textarea.addEventListener('input', (e) => {
            this.onSectionModified(fullKey, e.target.value);
            this.markSectionAsModified(section, fullKey);
        });

        return section;
    }

    renderUserMessagesEditor() {
        const container = document.getElementById('user_messages_editor');
        if (!container) return;

        container.innerHTML = '';

        Object.entries(this.prompts.user_messages || {}).forEach(([key, message]) => {
            const section = document.createElement('div');
            section.className = 'section-editor';
            
            section.innerHTML = `
                <div class="section-editor-header">
                    <h3>
                        <i class="fas fa-comment"></i>
                        ${message.name}
                    </h3>
                    <div class="section-actions">
                        <button class="btn btn-sm btn-secondary" onclick="promptManager.resetUserMessage('${key}')">
                            <i class="fas fa-undo"></i> Réinitialiser
                        </button>
                    </div>
                </div>
                <p class="text-muted mb-2">${message.description}</p>
                <div class="prompt-meta mb-3">
                    <span class="endpoint-tag">${message.endpoint}</span>
                </div>
                <textarea 
                    data-user-message="${key}"
                    placeholder="Template du message utilisateur..."
                    rows="5"
                >${message.template || ''}</textarea>
                <div class="mt-2">
                    <small class="text-muted">
                        Variables disponibles: ${(message.variables || []).map(v => `{${v}}`).join(', ')}
                    </small>
                </div>
            `;

            const textarea = section.querySelector('textarea');
            textarea.addEventListener('input', (e) => {
                this.onUserMessageModified(key, e.target.value);
                this.markSectionAsModified(section, `user_message.${key}`);
            });

            container.appendChild(section);
        });
    }

    formatSectionName(sectionKey) {
        const names = {
            'reset_header': 'En-tête de Reset',
            'role_definition': 'Définition du Rôle',
            'focus_principal': 'Focus Principal',
            'instructions_speciales_template': 'Instructions Spéciales',
            'elements_critiques_template': 'Éléments Critiques',
            'points_ignorables_template': 'Points Ignorables',
            'defauts_frequents_template': 'Défauts Fréquents',
            'instructions_analyse': 'Instructions d\'Analyse',
            'regles_fondamentales': 'Règles Fondamentales',
            'criteres_severite': 'Critères de Sévérité',
            'format_descriptions': 'Format des Descriptions',
            'format_json': 'Format JSON',
            'important_notes': 'Notes Importantes',
            'commentaire_global_instructions': 'Instructions Commentaire Global',
            'rappel_obligatoire': 'Rappel Obligatoire',
            'regles_conflit': 'Règles de Conflit',
            'types_pieces_template': 'Types de Pièces',
            'instructions': 'Instructions',
            'criteres_identification': 'Critères d\'Identification',
            'tache_template': 'Modèle de Tâche',
            'criteres_evaluation': 'Critères d\'Évaluation',
            'donnees_entree_template': 'Données d\'Entrée',
            'mission': 'Mission',
            'categories_synthese': 'Catégories de Synthèse',
            'regles_categories_vides': 'Règles Catégories Vides',
            'bareme_notation': 'Barème de Notation',
            'criteres_notation': 'Critères de Notation',
            'regles_recommandations': 'Règles Recommandations',
            'important_final': 'Important Final'
        };
        
        return names[sectionKey] || sectionKey.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    }

    onSectionModified(sectionKey, value) {
        const [promptKey, sectionName] = sectionKey.split('.');
        if (!this.prompts.prompts[promptKey]) return;
        
        this.prompts.prompts[promptKey].sections[sectionName] = value;
        this.modifiedSections.add(sectionKey);
        this.updateUnsavedCount();
    }

    onUserMessageModified(messageKey, value) {
        if (!this.prompts.user_messages[messageKey]) return;
        
        this.prompts.user_messages[messageKey].template = value;
        this.modifiedSections.add(`user_message.${messageKey}`);
        this.updateUnsavedCount();
    }

    markSectionAsModified(sectionElement, sectionKey) {
        sectionElement.classList.add('modified');
        
        // Mettre à jour l'overview si on y est
        if (this.currentSection === 'overview') {
            this.renderPromptsList();
        }
    }

    updateUnsavedCount() {
        document.getElementById('unsavedChanges').textContent = this.modifiedSections.size;
    }

    resetSection(sectionKey) {
        const [promptKey, sectionName] = sectionKey.split('.');
        const originalValue = this.originalPrompts.prompts[promptKey]?.sections[sectionName] || '';
        
        // Remettre la valeur originale
        this.prompts.prompts[promptKey].sections[sectionName] = originalValue;
        
        // Mettre à jour le textarea
        const textarea = document.querySelector(`textarea[data-section="${sectionKey}"]`);
        if (textarea) {
            textarea.value = originalValue;
        }
        
        // Retirer des modifications
        this.modifiedSections.delete(sectionKey);
        
        // Retirer la classe modified
        const sectionElement = textarea?.closest('.section-editor');
        if (sectionElement) {
            sectionElement.classList.remove('modified');
        }
        
        this.updateUnsavedCount();
        this.showNotification('Section réinitialisée', 'success');
    }

    resetUserMessage(messageKey) {
        const originalValue = this.originalPrompts.user_messages[messageKey]?.template || '';
        
        // Remettre la valeur originale
        this.prompts.user_messages[messageKey].template = originalValue;
        
        // Mettre à jour le textarea
        const textarea = document.querySelector(`textarea[data-user-message="${messageKey}"]`);
        if (textarea) {
            textarea.value = originalValue;
        }
        
        // Retirer des modifications
        this.modifiedSections.delete(`user_message.${messageKey}`);
        
        // Retirer la classe modified
        const sectionElement = textarea?.closest('.section-editor');
        if (sectionElement) {
            sectionElement.classList.remove('modified');
        }
        
        this.updateUnsavedCount();
        this.showNotification('Message utilisateur réinitialisé', 'success');
    }

    async saveAll() {
        try {
            // Mettre à jour la date de dernière modification
            this.prompts.last_updated = new Date().toISOString().split('T')[0];

            // Appel API pour sauvegarder avec le type de parcours
            const response = await fetch(`/prompts?type=${this.currentParcoursType}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(this.prompts)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(`HTTP error! status: ${response.status} - ${errorData.detail || 'Erreur de sauvegarde'}`);
            }

            const result = await response.json();
            if (result.success) {
                // Réinitialiser les modifications
                this.originalPrompts = JSON.parse(JSON.stringify(this.prompts));
                this.modifiedSections.clear();

                // Retirer toutes les classes modified
                document.querySelectorAll('.section-editor.modified').forEach(element => {
                    element.classList.remove('modified');
                });

                this.updateUnsavedCount();
                this.renderOverview();

                this.showNotification(`✅ Configuration ${this.currentParcoursType} sauvegardée avec succès (${result.last_updated})`, 'success');
            } else {
                throw new Error(result.message || 'Erreur de sauvegarde');
            }
        } catch (error) {
            console.error('Erreur lors de la sauvegarde:', error);
            this.showNotification(`❌ Erreur lors de la sauvegarde: ${error.message}`, 'error');
        }
    }

    exportJson() {
        try {
            const dataStr = JSON.stringify(this.prompts, null, 2);
            const dataBlob = new Blob([dataStr], { type: 'application/json' });

            const link = document.createElement('a');
            link.href = URL.createObjectURL(dataBlob);
            const typeSuffix = this.currentParcoursType.toLowerCase() === 'ménage' ? 'menage' : 'voyageur';
            link.download = `prompts-config-${typeSuffix}-${new Date().toISOString().split('T')[0]}.json`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            this.showNotification(`Configuration ${this.currentParcoursType} exportée avec succès`, 'success');
        } catch (error) {
            console.error('Erreur lors de l\'export:', error);
            this.showNotification('Erreur lors de l\'export', 'error');
        }
    }

    triggerImport() {
        document.getElementById('importFile').click();
    }

    async importJson(event) {
        const file = event.target.files[0];
        if (!file) return;

        try {
            const text = await file.text();
            const importedData = JSON.parse(text);
            
            // Validation basique
            if (!importedData.prompts && !importedData.user_messages) {
                throw new Error('Format de fichier invalide');
            }
            
            // Confirmer l'import
            if (this.modifiedSections.size > 0) {
                if (!confirm('Vous avez des modifications non sauvegardées. Continuer l\'import ?')) {
                    return;
                }
            }
            
            // Remplacer les données
            this.prompts = importedData;
            this.originalPrompts = JSON.parse(JSON.stringify(importedData));
            this.modifiedSections.clear();
            
            // Re-render l'interface
            this.renderOverview();
            this.renderAllEditors();
            
            this.showNotification('Configuration importée avec succès', 'success');
        } catch (error) {
            console.error('Erreur lors de l\'import:', error);
            this.showNotification('Erreur lors de l\'import: ' + error.message, 'error');
        }
        
        // Reset le file input
        event.target.value = '';
    }

    updatePreviewPromptSelect() {
        const select = document.getElementById('previewPromptSelect');
        select.innerHTML = '<option value="">-- Choisir un prompt --</option>';
        
        // Ajouter les prompts système
        Object.entries(this.prompts.prompts || {}).forEach(([key, prompt]) => {
            const option = document.createElement('option');
            option.value = key;
            option.textContent = prompt.name;
            select.appendChild(option);
        });
        
        // Ajouter les messages utilisateur
        Object.entries(this.prompts.user_messages || {}).forEach(([key, message]) => {
            const option = document.createElement('option');
            option.value = `user_message.${key}`;
            option.textContent = `[USER] ${message.name}`;
            select.appendChild(option);
        });
    }

    updatePreviewVariables() {
        const select = document.getElementById('previewPromptSelect');
        const variablesTextarea = document.getElementById('previewVariables');
        
        if (!select.value) {
            variablesTextarea.value = '';
            return;
        }
        
        let variables = [];
        
        if (select.value.startsWith('user_message.')) {
            const messageKey = select.value.replace('user_message.', '');
            const message = this.prompts.user_messages[messageKey];
            variables = message?.variables || [];
        } else {
            const prompt = this.prompts.prompts[select.value];
            variables = prompt?.variables || [];
        }
        
        // Générer un exemple JSON
        const exampleData = {};
        variables.forEach(variable => {
            switch (variable) {
                case 'piece_nom':
                    exampleData[variable] = 'Cuisine';
                    break;
                case 'logement_id':
                    exampleData[variable] = '1745691114127x167355942685376500';
                    break;
                case 'commentaire_ia':
                    exampleData[variable] = 'Attention particulière aux détails de propreté';
                    break;
                case 'elements_critiques':
                    exampleData[variable] = ['• Joints silicone évier', '• État robinetterie', '• Évacuations'];
                    break;
                case 'points_ignorables':
                    exampleData[variable] = ['• Petites traces sur murs', '• Variations couleur joints'];
                    break;
                case 'defauts_frequents':
                    exampleData[variable] = ['• Moisissures sous évier', '• Joints noircis', '• Traces de calcaire'];
                    break;
                case 'etape_task_name':
                    exampleData[variable] = 'Vider le lave-vaisselle';
                    break;
                case 'etape_consigne':
                    exampleData[variable] = 'vider la vaisselle';
                    break;
                case 'etape_id':
                    exampleData[variable] = '1745857142659x605188923525693400';
                    break;
                case 'total_issues':
                    exampleData[variable] = 3;
                    break;
                case 'general_issues':
                    exampleData[variable] = 2;
                    break;
                case 'etapes_issues':
                    exampleData[variable] = 1;
                    break;
                case 'room_types_list':
                    exampleData[variable] = ['cuisine', 'salle_de_bain', 'chambre', 'salon'];
                    break;
                case 'room_descriptions':
                    exampleData[variable] = ['- cuisine: Cuisine 🍽️', '- salle_de_bain: Salle de bain 🚿'];
                    break;
                case 'issues_summary_json':
                    exampleData[variable] = JSON.stringify([{
                        piece_name: "Cuisine 🍽️",
                        piece_id: "1745856961367x853186102447308800",
                        room_type: "cuisine",
                        global_score: 7,
                        global_status: "attention",
                        issues: [{
                            description: "Traces de graisse visibles sur la hotte aspirante",
                            category: "cleanliness",
                            severity: "medium",
                            confidence: 85
                        }]
                    }], null, 2);
                    break;
                default:
                    exampleData[variable] = `exemple_${variable}`;
            }
        });
        
        variablesTextarea.value = JSON.stringify(exampleData, null, 2);
    }

    generatePreview() {
        const select = document.getElementById('previewPromptSelect');
        const variablesInput = document.getElementById('previewVariables');
        const previewContent = document.getElementById('previewContent');
        
        if (!select.value) {
            this.showNotification('Veuillez sélectionner un prompt', 'warning');
            return;
        }
        
        try {
            let variables = {};
            if (variablesInput.value.trim()) {
                variables = JSON.parse(variablesInput.value);
            }
            
            let generatedPrompt = '';
            
            if (select.value.startsWith('user_message.')) {
                // Message utilisateur
                const messageKey = select.value.replace('user_message.', '');
                const message = this.prompts.user_messages[messageKey];
                generatedPrompt = this.replaceVariables(message.template || '', variables);
            } else {
                // Prompt système
                const prompt = this.prompts.prompts[select.value];
                generatedPrompt = this.buildFullPrompt(prompt, variables);
            }
            
            previewContent.textContent = generatedPrompt;
            
            // Highlighter le code si Prism est disponible
            if (window.Prism) {
                Prism.highlightElement(previewContent);
            }
            
        } catch (error) {
            console.error('Erreur lors de la génération:', error);
            this.showNotification('Erreur dans le JSON des variables: ' + error.message, 'error');
        }
    }

    buildFullPrompt(prompt, variables) {
        let fullPrompt = '';
        
        Object.entries(prompt.sections || {}).forEach(([sectionKey, content]) => {
            if (sectionKey.includes('template')) {
                // Section avec template - remplacer les variables
                fullPrompt += this.replaceVariables(content, variables) + '\n\n';
            } else {
                // Section normale
                fullPrompt += content + '\n\n';
            }
        });
        
        return fullPrompt.trim();
    }

    replaceVariables(template, variables) {
        let result = template;
        
        // Remplacer les variables simples {variable}
        Object.entries(variables).forEach(([key, value]) => {
            const regex = new RegExp(`\\{${key}\\}`, 'g');
            
            if (Array.isArray(value)) {
                // Pour les listes, joindre avec des retours à la ligne
                result = result.replace(regex, value.join('\n'));
            } else {
                result = result.replace(regex, String(value));
            }
        });
        
        return result;
    }

    showNotification(message, type = 'info', duration = 5000) {
        const container = document.getElementById('notifications');
        
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        
        const icons = {
            success: 'fas fa-check-circle',
            warning: 'fas fa-exclamation-triangle',
            error: 'fas fa-times-circle',
            info: 'fas fa-info-circle'
        };
        
        const titles = {
            success: 'Succès',
            warning: 'Attention',
            error: 'Erreur',
            info: 'Information'
        };
        
        notification.innerHTML = `
            <i class="${icons[type]} notification-icon"></i>
            <div class="notification-content">
                <div class="notification-title">${titles[type]}</div>
                <div class="notification-message">${message}</div>
            </div>
            <button class="notification-close">
                <i class="fas fa-times"></i>
            </button>
        `;
        
        const closeBtn = notification.querySelector('.notification-close');
        closeBtn.addEventListener('click', () => {
            notification.remove();
        });
        
        container.appendChild(notification);
        
        // Auto-remove après la durée spécifiée
        if (duration > 0) {
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.remove();
                }
            }, duration);
        }
    }
}

// Initialisation de l'application
let promptManager;

document.addEventListener('DOMContentLoaded', () => {
    promptManager = new PromptManager();
});

// Exposer globalement pour les onclick dans le HTML
window.promptManager = promptManager; 