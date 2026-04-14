targetScope = 'resourceGroup'

@description('リソースのデプロイ先リージョン')
param location string

@description('AI Services アカウント名（グローバルで一意）')
param accountName string

@description('Foundry プロジェクト名')
param projectName string = 'foundry-agent-eval'

@description('デプロイするモデル名（例: gpt-5.4, gpt-4.1, gpt-4o）')
param modelName string = 'gpt-5.4'

@description('モデルデプロイメント名（.env の MODEL_DEPLOYMENT_NAME に対応）')
param modelDeploymentName string = modelName

@description('モデルバージョン')
param modelVersion string = '2026-03-05'

@description('モデルの SKU 名')
param modelSkuName string = 'GlobalStandard'

@description('モデルの TPM キャパシティ（千トークン/分）')
param modelCapacity int = 10

@description('デプロイ実行者のプリンシパル ID（Azure AI User ロール付与用）')
param deployerPrincipalId string

var commonTags = {
  SecurityControl: 'Ignore'
  CostControl: 'Ignore'
}

// AI Services アカウント（Foundry のホスト）
resource aiServices 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  tags: commonTags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: accountName
    allowProjectManagement: true
    disableLocalAuth: false
  }
}

// Foundry プロジェクト
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: aiServices
  name: projectName
  location: location
  tags: commonTags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

// モデルデプロイメント
resource modelDeploy 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: aiServices
  name: modelDeploymentName
  sku: {
    name: modelSkuName
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

// --- RBAC: Azure AI User ロール ---
// https://aka.ms/FoundryPermissions
var azureAiUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

// デプロイ実行者に Azure AI User を付与
resource roleDeployer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiServices
  name: guid(aiServices.id, deployerPrincipalId, azureAiUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUserRoleId)
    principalId: deployerPrincipalId
    principalType: 'User'
  }
}

// プロジェクト Managed Identity に Azure AI User を付与
resource roleProjectMi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiServices
  name: guid(aiServices.id, projectName, 'project-mi', azureAiUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUserRoleId)
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

@description('.env の PROJECT_ENDPOINT に設定する値')
output projectEndpoint string = 'https://${accountName}.services.ai.azure.com/api/projects/${projectName}'

@description('モデルデプロイメント名')
output modelDeployment string = modelDeploy.name
