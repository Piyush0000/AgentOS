const { Sequelize, DataTypes } = require('sequelize');
const path = require('path');

const dbUrl = process.env.DATABASE_URL || `sqlite:${path.join(__dirname, '..', 'agentos.db')}`;

console.log(`Connecting Sequelize to: ${dbUrl}`);

const sequelize = new Sequelize(dbUrl, {
  logging: false,
  define: {
    timestamps: false // We manage created_at / updated_at manually to align with SQLAlchemy
  }
});

// User Model
const User = sequelize.define('User', {
  id: {
    type: DataTypes.STRING,
    primaryKey: true,
    defaultValue: () => require('crypto').randomUUID()
  },
  name: {
    type: DataTypes.STRING,
    allowNull: false
  },
  email: {
    type: DataTypes.STRING,
    allowNull: false,
    unique: true
  },
  password_hash: {
    type: DataTypes.STRING,
    allowNull: false
  },
  created_at: {
    type: DataTypes.DATE,
    defaultValue: Sequelize.NOW
  }
}, {
  tableName: 'users'
});

// Agent Manifest Model
const AgentManifest = sequelize.define('AgentManifest', {
  id: {
    type: DataTypes.STRING,
    primaryKey: true
  },
  name: {
    type: DataTypes.STRING,
    allowNull: false
  },
  description: {
    type: DataTypes.TEXT,
    allowNull: true
  },
  created_at: {
    type: DataTypes.DATE,
    defaultValue: Sequelize.NOW
  }
}, {
  tableName: 'agent_manifests'
});

// Agent Version Model
const AgentVersion = sequelize.define('AgentVersion', {
  id: {
    type: DataTypes.INTEGER,
    primaryKey: true,
    autoIncrement: true
  },
  manifest_id: {
    type: DataTypes.STRING,
    allowNull: false
  },
  version: {
    type: DataTypes.INTEGER,
    allowNull: false
  },
  manifest_yaml: {
    type: DataTypes.TEXT,
    allowNull: false
  },
  created_at: {
    type: DataTypes.DATE,
    defaultValue: Sequelize.NOW
  }
}, {
  tableName: 'agent_versions'
});

// Agent Instance Model
const AgentInstance = sequelize.define('AgentInstance', {
  id: {
    type: DataTypes.STRING,
    primaryKey: true,
    defaultValue: () => require('crypto').randomUUID()
  },
  manifest_id: {
    type: DataTypes.STRING,
    allowNull: false
  },
  version: {
    type: DataTypes.INTEGER,
    allowNull: false
  },
  status: {
    type: DataTypes.STRING,
    defaultValue: 'REGISTERED'
  },
  user_id: {
    type: DataTypes.STRING,
    allowNull: true
  },
  created_at: {
    type: DataTypes.DATE,
    defaultValue: Sequelize.NOW
  },
  updated_at: {
    type: DataTypes.DATE,
    defaultValue: Sequelize.NOW
  }
}, {
  tableName: 'agent_instances'
});

// Task Model
const Task = sequelize.define('Task', {
  id: {
    type: DataTypes.STRING,
    primaryKey: true,
    defaultValue: () => 'task_' + require('crypto').randomBytes(4).toString('hex')
  },
  instance_id: {
    type: DataTypes.STRING,
    allowNull: false
  },
  user_id: {
    type: DataTypes.STRING,
    allowNull: true
  },
  input_data: {
    type: DataTypes.TEXT,
    allowNull: false
  },
  status: {
    type: DataTypes.STRING,
    defaultValue: 'QUEUED'
  },
  priority: {
    type: DataTypes.STRING,
    defaultValue: 'medium'
  },
  max_tokens: {
    type: DataTypes.INTEGER,
    allowNull: true
  },
  max_usd: {
    type: DataTypes.FLOAT,
    allowNull: true
  },
  output_data: {
    type: DataTypes.TEXT,
    allowNull: true
  },
  error_message: {
    type: DataTypes.TEXT,
    allowNull: true
  },
  llm_provider: {
    type: DataTypes.STRING,
    allowNull: true
  },
  llm_api_key: {
    type: DataTypes.TEXT,
    allowNull: true
  },
  created_at: {
    type: DataTypes.DATE,
    defaultValue: Sequelize.NOW
  },
  updated_at: {
    type: DataTypes.DATE,
    defaultValue: Sequelize.NOW
  }
}, {
  tableName: 'tasks'
});

// Checkpoint Model
const Checkpoint = sequelize.define('Checkpoint', {
  id: {
    type: DataTypes.INTEGER,
    primaryKey: true,
    autoIncrement: true
  },
  task_id: {
    type: DataTypes.STRING,
    allowNull: false
  },
  step_index: {
    type: DataTypes.INTEGER,
    allowNull: false
  },
  state_data: {
    type: DataTypes.TEXT,
    allowNull: false
  },
  created_at: {
    type: DataTypes.DATE,
    defaultValue: Sequelize.NOW
  }
}, {
  tableName: 'checkpoints'
});

// Tool Call Model
const ToolCall = sequelize.define('ToolCall', {
  id: {
    type: DataTypes.STRING,
    primaryKey: true,
    defaultValue: () => require('crypto').randomUUID()
  },
  task_id: {
    type: DataTypes.STRING,
    allowNull: false
  },
  tool_name: {
    type: DataTypes.STRING,
    allowNull: false
  },
  arguments: {
    type: DataTypes.TEXT,
    allowNull: false
  },
  result: {
    type: DataTypes.TEXT,
    allowNull: true
  },
  status: {
    type: DataTypes.STRING,
    defaultValue: 'ALLOWED'
  },
  created_at: {
    type: DataTypes.DATE,
    defaultValue: Sequelize.NOW
  }
}, {
  tableName: 'tool_calls'
});

// Associations
User.hasMany(AgentInstance, { foreignKey: 'user_id', as: 'instances' });
AgentInstance.belongsTo(User, { foreignKey: 'user_id', as: 'user' });

User.hasMany(Task, { foreignKey: 'user_id', as: 'tasks' });
Task.belongsTo(User, { foreignKey: 'user_id', as: 'user' });

AgentInstance.hasMany(Task, { foreignKey: 'instance_id', as: 'tasks' });
Task.belongsTo(AgentInstance, { foreignKey: 'instance_id', as: 'instance' });

Task.hasMany(Checkpoint, { foreignKey: 'task_id', as: 'checkpoints' });
Checkpoint.belongsTo(Task, { foreignKey: 'task_id', as: 'task' });

Task.hasMany(ToolCall, { foreignKey: 'task_id', as: 'tool_calls' });
ToolCall.belongsTo(Task, { foreignKey: 'task_id', as: 'task' });

module.exports = {
  sequelize,
  User,
  AgentManifest,
  AgentVersion,
  AgentInstance,
  Task,
  Checkpoint,
  ToolCall
};
