targetScope = 'resourceGroup'

@description('Azure region allowed by the Student subscription policy.')
param location string = 'polandcentral'

@description('Globally unique prefix. Lowercase letters and digits only.')
@minLength(5)
@maxLength(18)
param namePrefix string

param appServiceName string = 'onda-api-omid-2026'
param postgresAdminUser string = 'ondaadmin'
param vmAdminUser string = 'ondaadmin'

@secure()
param postgresAdminPassword string

@secure()
param apiJwtSecret string

@secure()
param jitsiJwtSecret string

@description('Public outbound IPv4 addresses of the existing App Service.')
param backendOutboundIps array

@description('Optional developer IPv4 address used only while running migrations.')
param developerIp string = ''

@description('SSH public key for emergency VM administration.')
param sshPublicKey string

@description('CIDR allowed to use SSH. Use your current public IPv4 with /32.')
param sshSourceCidr string

@description('Email used by Let\'s Encrypt for the Jitsi TLS certificate.')
param letsEncryptEmail string
param jitsiReleaseTag string = 'stable-11146-2'
param jitsiVmSize string = 'Standard_B2als_v2'

var postgresServerName = '${namePrefix}-pg'
var keyVaultName = '${namePrefix}-kv'
var publicIpName = '${namePrefix}-jitsi-pip'
var jitsiDnsLabel = '${namePrefix}-meet'
var jitsiFqdn = '${jitsiDnsLabel}.${location}.cloudapp.azure.com'
var databaseUrl = 'postgresql+asyncpg://${postgresAdminUser}:${uriComponent(postgresAdminPassword)}@${postgresServer.properties.fullyQualifiedDomainName}:5432/onda?ssl=require'

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
    sku: {
      family: 'A'
      name: 'standard'
    }
  }
}

resource apiJwtSecretResource 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'onda-api-jwt-secret'
  properties: {
    value: apiJwtSecret
  }
}

resource jitsiJwtSecretResource 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'onda-jitsi-jwt-secret'
  properties: {
    value: jitsiJwtSecret
  }
}

resource databaseUrlSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'onda-database-url'
  properties: {
    value: databaseUrl
  }
}

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresServerName
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    availabilityZone: '1'
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      publicNetworkAccess: 'Enabled'
    }
    storage: {
      storageSizeGB: 32
      autoGrow: 'Enabled'
    }
  }
}

resource ondaDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgresServer
  name: 'onda'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource backendFirewallRules 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = [
  for (ip, index) in backendOutboundIps: {
    parent: postgresServer
    name: 'app-service-${index}'
    properties: {
      startIpAddress: ip
      endIpAddress: ip
    }
  }
]

resource developerFirewallRule 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = if (!empty(developerIp)) {
  parent: postgresServer
  name: 'temporary-developer-ip'
  properties: {
    startIpAddress: developerIp
    endIpAddress: developerIp
  }
}

resource jitsiNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${namePrefix}-jitsi-nsg'
  location: location
  properties: {
    securityRules: [
      {
        name: 'https'
        properties: {
          priority: 100
          access: 'Allow'
          direction: 'Inbound'
          protocol: 'Tcp'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRanges: [
            '80'
            '443'
          ]
        }
      }
      {
        name: 'jitsi-media'
        properties: {
          priority: 110
          access: 'Allow'
          direction: 'Inbound'
          protocol: 'Udp'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '10000'
        }
      }
      {
        name: 'restricted-ssh'
        properties: {
          priority: 120
          access: 'Allow'
          direction: 'Inbound'
          protocol: 'Tcp'
          sourceAddressPrefix: sshSourceCidr
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '22'
        }
      }
    ]
  }
}

resource jitsiVnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${namePrefix}-vnet'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.42.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'jitsi'
        properties: {
          addressPrefix: '10.42.1.0/24'
          networkSecurityGroup: {
            id: jitsiNsg.id
          }
        }
      }
    ]
  }
}

resource jitsiPublicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: publicIpName
  location: location
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    dnsSettings: {
      domainNameLabel: jitsiDnsLabel
    }
  }
}

resource jitsiNic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: '${namePrefix}-jitsi-nic'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'primary'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: resourceId('Microsoft.Network/virtualNetworks/subnets', jitsiVnet.name, 'jitsi')
          }
          publicIPAddress: {
            id: jitsiPublicIp.id
          }
        }
      }
    ]
  }
}

var cloudInitTemplate = loadTextContent('jitsi/cloud-init.yaml')
var cloudInitWithVault = replace(cloudInitTemplate, '__KEY_VAULT_NAME__', vault.name)
var cloudInitWithDomain = replace(cloudInitWithVault, '__JITSI_FQDN__', jitsiFqdn)
var cloudInitWithEmail = replace(cloudInitWithDomain, '__LETSENCRYPT_EMAIL__', letsEncryptEmail)
var cloudInitWithAppId = replace(cloudInitWithEmail, '__JITSI_APP_ID__', 'onda')
var cloudInitWithRelease = replace(cloudInitWithAppId, '__JITSI_RELEASE_TAG__', jitsiReleaseTag)
var cloudInit = replace(cloudInitWithRelease, '__JITSI_PUBLIC_IP__', jitsiPublicIp.properties.ipAddress)

resource jitsiVm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: '${namePrefix}-jitsi-vm'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    hardwareProfile: {
      vmSize: jitsiVmSize
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: jitsiNic.id
          properties: {
            primary: true
          }
        }
      ]
    }
    osProfile: {
      computerName: 'onda-jitsi'
      adminUsername: vmAdminUser
      customData: base64(cloudInit)
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${vmAdminUser}/.ssh/authorized_keys'
              keyData: sshPublicKey
            }
          ]
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS'
        }
      }
    }
  }
}

resource jitsiKeyVaultRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, jitsiVm.id, 'key-vault-secrets-user')
  scope: vault
  properties: {
    principalId: jitsiVm.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'
    )
  }
}

output appServiceName string = appServiceName
output keyVaultName string = vault.name
output postgresHost string = postgresServer.properties.fullyQualifiedDomainName
output jitsiUrl string = 'https://${jitsiFqdn}'
output jitsiVmName string = jitsiVm.name
output apiJwtSecretUri string = apiJwtSecretResource.properties.secretUri
output jitsiJwtSecretUri string = jitsiJwtSecretResource.properties.secretUri
output databaseUrlSecretUri string = databaseUrlSecret.properties.secretUri
