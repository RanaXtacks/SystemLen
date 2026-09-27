const path = require("path");
const fs = require("fs");

const { parseSqlDdl } = require("./out/engine/schema/sqlParser");
const { parsePrismaSchema } = require("./out/engine/schema/prismaParser");
const { parseActiveRecordSchema } = require("./out/engine/schema/activeRecordParser");
const { PythonCodeAdapter } = require("./out/engine/adapters/python");
const { JavaScriptCodeAdapter } = require("./out/engine/adapters/javascript");
const { GolangCodeAdapter } = require("./out/engine/adapters/golang");
const { JavaCodeAdapter } = require("./out/engine/adapters/java");
const { RubyCodeAdapter } = require("./out/engine/adapters/ruby");
const { PhpCodeAdapter } = require("./out/engine/adapters/php");
const { UniversalSqlAdapter } = require("./out/engine/adapters/universalSql");
const { GraphBuilder } = require("./out/engine/graph/graphBuilder");
const { NativeImpactEngine } = require("./out/engine/graph/impactEngine");

let failures = 0;
function assert(condition, message) {
  if (!condition) {
    console.error("FAIL:", message);
    failures++;
  } else {
    console.log("PASS:", message);
  }
}

console.log("=== 1. Testing SQL Schema Parser ===");
const sqlSample = `
CREATE TABLE users (
  id INT PRIMARY KEY,
  org_id INT REFERENCES organizations(id),
  email VARCHAR(255)
);
CREATE TABLE orders (
  id INT PRIMARY KEY,
  user_id INT,
  amount DECIMAL,
  CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id)
);
`;
const sqlCatalog = parseSqlDdl(sqlSample, "schema.sql");
const tables = Object.values(sqlCatalog.tables);
assert(tables.length === 2, "Parsed 2 tables from SQL");
const usersTable = sqlCatalog.tables["users"];
const ordersTable = sqlCatalog.tables["orders"];
assert(usersTable && usersTable.columns.length === 3, "users table has 3 columns");
assert(ordersTable && ordersTable.foreignKeys.length === 1, "orders table has 1 FK to users");
assert(ordersTable.foreignKeys[0].targetTable === "users", "FK target is users");

console.log("\n=== 2. Testing Prisma Schema Parser ===");
const prismaSample = `
model User {
  id    Int     @id @default(autoincrement())
  email String  @unique
  posts Post[]
}

model Post {
  id       Int  @id @default(autoincrement())
  authorId Int
  author   User @relation(fields: [authorId], references: [id])
}
`;
const prismaCatalog = parsePrismaSchema(prismaSample, "schema.prisma");
const prismaTables = Object.values(prismaCatalog.tables);
assert(prismaTables.length === 2, "Parsed 2 models from Prisma");
const postModel = prismaCatalog.tables["post"] || prismaCatalog.tables["posts"];
assert(postModel && postModel.foreignKeys.length === 1, "Post model has FK to user");

console.log("\n=== 3. Testing Rails ActiveRecord Schema Parser ===");
const arSample = `
ActiveRecord::Schema.define(version: 2023_01_01_000000) do
  create_table "accounts", force: :cascade do |t|
    t.string "name"
  end

  create_table "members", force: :cascade do |t|
    t.bigint "account_id"
    t.string "role"
  end

  add_foreign_key "members", "accounts"
end
`;
const arCatalog = parseActiveRecordSchema(arSample, "db/schema.rb");
const arTables = Object.values(arCatalog.tables);
assert(arTables.length === 2, "Parsed 2 tables from Rails schema.rb");
const membersTable = arCatalog.tables["members"];
assert(membersTable && membersTable.foreignKeys.length === 1, "members has FK to accounts");

console.log("\n=== 4. Testing Go Adapter ===");
const goAdapter = new GolangCodeAdapter();
const goCode = `
package service

import "gorm.io/gorm"

func GetUserOrders(db *gorm.DB, userId int) []Order {
    var orders []Order
    db.Table("orders").Where("user_id = ?", userId).Find(&orders)
    return orders
}

func RawQuery(db *gorm.DB) {
    db.Raw("SELECT id, email FROM users WHERE active = true")
}
`;
const goResult = goAdapter.scanFile("service/order.go", goCode, new Set(["orders", "users"]));
assert(goResult.edges.some(e => e.target === "table:orders"), "Go adapter detected table:orders");
assert(goResult.edges.some(e => e.target === "table:users"), "Go adapter detected table:users via Raw SQL");

console.log("\n=== 5. Testing Java Adapter ===");
const javaAdapter = new JavaCodeAdapter();
const javaCode = `
package com.example.repo;

import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.CrudRepository;

public interface UserRepository extends CrudRepository<User, Long> {
    @Query("SELECT u FROM users u WHERE u.email = :email")
    User findByEmail(String email);

    List<User> findByStatus(String status);
}
`;
const javaResult = javaAdapter.scanFile("com/example/repo/UserRepository.java", javaCode, new Set(["users"]));
assert(javaResult.edges.some(e => e.target === "table:users"), "Java adapter detected @Query users table");

console.log("\n=== 6. Testing Ruby Adapter ===");
const rubyAdapter = new RubyCodeAdapter();
const rubyCode = `
class OrdersController < ApplicationController
  def index
    @orders = Order.where(user_id: current_user.id)
    @users = ActiveRecord::Base.connection.execute("SELECT * FROM users")
  end
end
`;
const rubyResult = rubyAdapter.scanFile("app/controllers/orders_controller.rb", rubyCode, new Set(["orders", "users"]));
assert(rubyResult.edges.some(e => e.target === "table:orders" || e.target === "table:order"), "Ruby adapter detected Order model");
assert(rubyResult.edges.some(e => e.target === "table:users"), "Ruby adapter detected users table in raw SQL");

console.log("\n=== 7. Testing PHP Adapter ===");
const phpAdapter = new PhpCodeAdapter();
const phpCode = `
<?php
namespace App\\Http\\Controllers;

use Illuminate\\Support\\Facades\\DB;

class UserController extends Controller {
    public function getActiveUsers() {
        return DB::table('users')->where('active', 1)->get();
    }
}
`;
const phpResult = phpAdapter.scanFile("app/Http/Controllers/UserController.php", phpCode, new Set(["users"]));
assert(phpResult.edges.some(e => e.target === "table:users"), "PHP adapter detected DB::table('users')");

console.log("\n=== 8. Testing Graph Builder & Native Impact Engine ===");
const builder = new GraphBuilder();
builder.addSchemaCatalog(sqlCatalog);
builder.addCodeAnalysis(goResult.nodes, goResult.edges);
builder.addCodeAnalysis(rubyResult.nodes, rubyResult.edges);

const graph = builder.build();
assert(graph.nodes.some(n => n.id === "table:users"), "Graph has table:users node");
assert(graph.nodes.some(n => n.id === "table:orders"), "Graph has table:orders node");

const impactEngine = new NativeImpactEngine(graph);
const blast = impactEngine.blastRadius("users", 2);
assert(blast.impacted_tables.some(t => t.name === "orders"), "Blast radius includes downstream table orders (via FK)");
assert(blast.impacted_functions.length > 0, "Blast radius includes touching code functions");

console.log("\n=================================");
if (failures === 0) {
  console.log("ALL UNIVERSAL ENGINE TESTS PASSED!");
  process.exit(0);
} else {
  console.error(`FAILED: ${failures} test failures!`);
  process.exit(1);
}
