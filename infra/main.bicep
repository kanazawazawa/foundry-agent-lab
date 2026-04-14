targetScope = 'subscription'

@description('デプロイ先リージョン')
param location string = 'swedencentral'

@description('デプロイするモデル名（例: gpt-5.4, gpt-4.1-mini, gpt-4o）')
param modelName string = 'gpt-5.4'

@description('モデルバージョン')
param modelVersion string = '2026-03-05'

@description('モデルの SKU 名')
param modelSkuName string = 'GlobalStandard'

@description('モデルの TPM キャパシティ（千トークン/分）')
param modelCapacity int = 10

// デプロイのたびに新しい環境を作成（utcNow は毎回異なる値を返す）
param timestamp string = utcNow()
var suffix = uniqueString(timestamp)
var rgName = 'rg-agent-eval-demo-${suffix}'
var accountName = 'ai-eval-${suffix}'
var projectName = 'foundry-agent-eval'

var commonTags = {
  SecurityControl: 'Ignore'
  CostControl: 'Ignore'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: rgName
  location: location
  tags: commonTags
}

@description('デプロイ実行者のプリンシパル ID（az ad signed-in-user show --query id）')
param deployerPrincipalId string

module foundry 'resources.bicep' = {
  scope: rg
  params: {
    location: location
    accountName: accountName
    projectName: projectName
    modelName: modelName
    modelDeploymentName: modelName
    modelVersion: modelVersion
    modelSkuName: modelSkuName
    modelCapacity: modelCapacity
    deployerPrincipalId: deployerPrincipalId
  }
}

output resourceGroupName string = rg.name
output projectEndpoint string = foundry.outputs.projectEndpoint
output modelDeploymentName string = modelName
